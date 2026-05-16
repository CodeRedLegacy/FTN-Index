import requests
from bs4 import BeautifulSoup
import os
from flask import Flask, jsonify
from flask_cors import CORS
import datetime
from collections import deque
import re
import logging
from google import genai

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

score_history = deque(maxlen=7)

# ---------- SCRAPING HELPERS ----------
def fetch_soup(url, timeout=10):
    r = requests.get(url, timeout=timeout)
    return BeautifulSoup(r.text, 'html.parser')

def extract_text(soup):
    # Try common containers in order
    for selector in ['article', 'div#content', 'body']:
        tag = soup.select_one(selector) if '#' not in selector else soup.find('div', id='content')
        if tag:
            return tag.get_text()[:4000]  # keep 4000 chars max per document
    return ""

# ---------- SOURCE: FED SPEECHES ----------
def scrape_fed_speeches():
    try:
        soup = fetch_soup("https://www.federalreserve.gov/newsevents/speeches.htm")
        items = soup.select('a[href*="speech"]')
        sources = []
        for a in items[:3]:  # latest 3
            href = a.get('href')
            if href:
                full_url = "https://www.federalreserve.gov" + href if href.startswith('/') else href
                title = a.get_text(strip=True)
                sources.append({'type': 'speech', 'title': title, 'url': full_url})
        logging.info(f"Scraped {len(sources)} speech links")
        return sources
    except Exception as e:
        logging.error(f"Speeches scrape error: {e}")
        return []

# ---------- SOURCE: FOMC PRESS RELEASES (STATEMENTS) ----------
def scrape_fomc_statements():
    try:
        soup = fetch_soup("https://www.federalreserve.gov/newsevents/pressreleases.htm")
        # Press release links often contain 'pressrelease' in href
        items = soup.select('a[href*="pressrelease"]')
        sources = []
        for a in items[:2]:  # latest 2 (usually only one per meeting)
            href = a.get('href')
            if href:
                full_url = "https://www.federalreserve.gov" + href if href.startswith('/') else href
                title = a.get_text(strip=True)
                sources.append({'type': 'fomc_statement', 'title': title, 'url': full_url})
        logging.info(f"Scraped {len(sources)} FOMC statement links")
        return sources
    except Exception as e:
        logging.error(f"FOMC statements scrape error: {e}")
        return []

# ---------- SOURCE: FOMC MINUTES ----------
def scrape_fomc_minutes():
    try:
        soup = fetch_soup("https://www.federalreserve.gov/monetarypolicy/fomcminutes.htm")
        # Minutes links often contain 'fomcminutes' in href
        items = soup.select('a[href*="fomcminutes"]')
        sources = []
        for a in items[:1]:  # latest 1 (only one set of minutes per meeting)
            href = a.get('href')
            if href:
                full_url = "https://www.federalreserve.gov" + href if href.startswith('/') else href
                title = a.get_text(strip=True)
                sources.append({'type': 'fomc_minutes', 'title': title, 'url': full_url})
        logging.info(f"Scraped {len(sources)} FOMC minutes links")
        return sources
    except Exception as e:
        logging.error(f"FOMC minutes scrape error: {e}")
        return []

# ---------- AI SCORING ----------
def score_text_with_ai(text):
    if not text:
        return None
    prompt = f"""
You are a Federal Reserve communication analyzer. Rate the following text on a scale from 0 (extremely dovish, suggesting rate cuts/easing) to 100 (extremely hawkish, suggesting rate hikes/tightening). Return ONLY the number, no explanation.

Text:
{text[:3000]}
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"temperature": 0, "max_output_tokens": 5}
        )
        score_str = response.text.strip()
        digits = re.findall(r'\d+', score_str)
        if digits:
            return max(0, min(100, int(digits[0])))
    except Exception as e:
        logging.error(f"Gemini API error: {e}")
    return None

# ---------- COMBINED PIPELINE ----------
def compute_daily_ftn():
    all_sources = []
    # Collect all source types
    all_sources.extend(scrape_fed_speeches())
    all_sources.extend(scrape_fomc_statements())
    all_sources.extend(scrape_fomc_minutes())

    scores = []
    total_chars = 0
    sources_detail = []

    for src in all_sources:
        try:
            soup = fetch_soup(src['url'])
            text = extract_text(soup)
            if text:
                score = score_text_with_ai(text)
                if score is not None:
                    scores.append(score)
                    total_chars += len(text)
                    sources_detail.append({
                        'type': src['type'],
                        'title': src['title'],
                        'url': src['url'],
                        'chars': len(text)
                    })
                    logging.info(f"Scored {src['type']}: {score}")
        except Exception as e:
            logging.error(f"Error processing {src['url']}: {e}")

    if not scores:
        return None, None, []

    # Compute raw FTN (average of individual document scores)
    raw = sum(scores) / len(scores)
    score_history.append(raw)
    smoothed = round(sum(score_history) / len(score_history), 1)

    # Confidence calculation
    num_sources = len(sources_detail)
    if num_sources >= 4 and total_chars > 8000:
        confidence = "HIGH"
    elif num_sources >= 2 and total_chars > 3000:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return smoothed, confidence, sources_detail

# ---------- ROUTES ----------
@app.route('/api/ftn_latest')
def ftn_latest():
    score, confidence, sources = compute_daily_ftn()
    if score is None:
        return jsonify({"error": "No data available"}), 500

    prev = list(score_history)
    change = round(score - prev[-2], 1) if len(prev) > 1 else 0

    return jsonify({
        "index": "F-Tone (FTN)",
        "score": score,
        "change": change,
        "confidence": confidence,
        "sources": sources,
        "timestamp": datetime.datetime.utcnow().isoformat()
    })

@app.route('/')
def home():
    return "F-Tone (FTN) Federal Reserve Tone Index is live. Use /api/ftn_latest"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
