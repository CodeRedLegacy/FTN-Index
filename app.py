import requests
from bs4 import BeautifulSoup
import os
from flask import Flask, jsonify
from flask_cors import CORS
import datetime
from collections import deque
import re
import logging

# ---------- AI PROVIDERS ----------
from groq import Groq
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
groq_client = None
if GROQ_API_KEY and GROQ_API_KEY.strip():
    groq_client = Groq(api_key=GROQ_API_KEY)
else:
    logging.warning("GROQ_API_KEY is empty or missing; Groq will be skipped.")

from google import genai
GEMINI_KEY_1 = os.environ.get("GEMINI_API_KEY_1")
GEMINI_KEY_2 = os.environ.get("GEMINI_API_KEY_2")
GEMINI_KEY_3 = os.environ.get("GEMINI_API_KEY_3")

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

score_history = deque(maxlen=7)

# ---------- HELPERS ----------
def fetch_soup(url, timeout=10):
    r = requests.get(url, timeout=timeout)
    return BeautifulSoup(r.text, 'html.parser')

def extract_text(soup):
    for selector in ['article', 'div#content', 'body']:
        if selector == 'div#content':
            tag = soup.find('div', id='content')
        else:
            tag = soup.select_one(selector)
        if tag:
            return tag.get_text()[:4000]
    return ""

def is_list_page(url):
    """Return True if the URL looks like an index/list page, not an individual document."""
    list_markers = [
        'speeches-testimony.htm', 'speeches.htm', 'pressreleases.htm',
        '2026-speeches.htm', '2026-press-fomc.htm', 'fomcminutes.htm',
        'pressreleases.htm', 'monetarypolicy/fomcminutes',
        '/newsevents/2026-',  # yearly list pages
    ]
    for marker in list_markers:
        if marker in url:
            return True
    return False

# ---------- SOURCE SCRAPERS (BROADER SELECTORS) ----------
def scrape_fed_speeches():
    try:
        soup = fetch_soup("https://www.federalreserve.gov/newsevents/speeches.htm")
        # Try multiple patterns: individual speech pages often contain the year and end in .htm
        patterns = [
            'a[href*="/speech/"]',      # /newsevents/speech/2026/...
            'a[href*="speech"]',         # broader catch-all
            'a[href$="a.htm"]',          # many speech pages end like ...0515a.htm
        ]
        sources = []
        for pattern in patterns:
            if len(sources) >= 3:
                break
            for a in soup.select(pattern):
                if len(sources) >= 3:
                    break
                href = a.get('href')
                if href:
                    full_url = "https://www.federalreserve.gov" + href if href.startswith('/') else href
                    if is_list_page(full_url) or full_url.endswith('.xml'):
                        continue
                    title = a.get_text(strip=True) or "Speech"
                    if not any(s['url'] == full_url for s in sources):
                        sources.append({'type': 'speech', 'title': title, 'url': full_url})
        logging.info(f"Scraped {len(sources)} speech links")
        return sources
    except Exception as e:
        logging.error(f"Speeches scrape error: {e}")
        return []

def scrape_fomc_statements():
    try:
        soup = fetch_soup("https://www.federalreserve.gov/newsevents/pressreleases.htm")
        patterns = [
            'a[href*="pressrelease"]',
            'a[href$="a.htm"]',
        ]
        sources = []
        for pattern in patterns:
            if len(sources) >= 2:
                break
            for a in soup.select(pattern):
                if len(sources) >= 2:
                    break
                href = a.get('href')
                if href:
                    full_url = "https://www.federalreserve.gov" + href if href.startswith('/') else href
                    if is_list_page(full_url):
                        continue
                    title = a.get_text(strip=True) or "FOMC Statement"
                    if not any(s['url'] == full_url for s in sources):
                        sources.append({'type': 'fomc_statement', 'title': title, 'url': full_url})
        logging.info(f"Scraped {len(sources)} FOMC statement links")
        return sources
    except Exception as e:
        logging.error(f"FOMC statements scrape error: {e}")
        return []

def scrape_fomc_minutes():
    try:
        soup = fetch_soup("https://www.federalreserve.gov/monetarypolicy/fomcminutes.htm")
        patterns = [
            'a[href*="fomcminutes"]',
            'a[href$="a.htm"]',
        ]
        sources = []
        for pattern in patterns:
            if len(sources) >= 1:
                break
            for a in soup.select(pattern):
                if len(sources) >= 1:
                    break
                href = a.get('href')
                if href:
                    full_url = "https://www.federalreserve.gov" + href if href.startswith('/') else href
                    if is_list_page(full_url):
                        continue
                    title = a.get_text(strip=True) or "FOMC Minutes"
                    if not any(s['url'] == full_url for s in sources):
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
    if groq_client:
        try:
            chat_completion = groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
                temperature=0,
                max_tokens=5
            )
            score_str = chat_completion.choices[0].message.content.strip()
            digits = re.findall(r'\d+', score_str)
            if digits:
                score = int(digits[0])
                logging.info(f"AI score (Groq): {score}")
                return max(0, min(100, score))
        except Exception as e:
            logging.warning(f"Groq failed ({e}), falling back to Gemini-1...")
    else:
        logging.info("Groq key not configured, skipping to Gemini...")
    if GEMINI_KEY_1:
        try:
            gemini_client = genai.Client(api_key=GEMINI_KEY_1)
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={"temperature": 0, "max_output_tokens": 5}
            )
            score_str = response.text.strip()
            digits = re.findall(r'\d+', score_str)
            if digits:
                score = int(digits[0])
                logging.info(f"AI score (Gemini-1): {score}")
                return max(0, min(100, score))
        except Exception as e:
            logging.warning(f"Gemini-1 failed ({e}), falling back to Gemini-2...")
    if GEMINI_KEY_2:
        try:
            gemini_client = genai.Client(api_key=GEMINI_KEY_2)
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={"temperature": 0, "max_output_tokens": 5}
            )
            score_str = response.text.strip()
            digits = re.findall(r'\d+', score_str)
            if digits:
                score = int(digits[0])
                logging.info(f"AI score (Gemini-2): {score}")
                return max(0, min(100, score))
        except Exception as e:
            logging.warning(f"Gemini-2 failed ({e}), falling back to Gemini-3...")
    if GEMINI_KEY_3:
        try:
            gemini_client = genai.Client(api_key=GEMINI_KEY_3)
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={"temperature": 0, "max_output_tokens": 5}
            )
            score_str = response.text.strip()
            digits = re.findall(r'\d+', score_str)
            if digits:
                score = int(digits[0])
                logging.info(f"AI score (Gemini-3): {score}")
                return max(0, min(100, score))
        except Exception as e:
            logging.error(f"All AI providers failed: {e}")
            return None
    logging.error("No Gemini API keys configured")
    return None

# ---------- COMBINED PIPELINE ----------
def compute_daily_ftn():
    all_sources = []
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
    raw = sum(scores) / len(scores)
    score_history.append(raw)
    smoothed = round(sum(score_history) / len(score_history), 1)
    num_sources = len(sources_detail)
    if num_sources >= 4 and total_chars > 8000:
        confidence = "HIGH"
    elif num_sources >= 2 and total_chars > 3000:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    return smoothed, confidence, sources_detail

# ---------- ROUTES ----------
@app.route('/health')
def health():
    return "OK"

@app.route('/ping')
def ping():
    score, confidence, sources = compute_daily_ftn()
    if score is None:
        return jsonify({"status": "error", "message": "No data"}), 500
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    return jsonify({"status": "ok", "score": score, "timestamp": ts})

@app.route('/api/ftn_latest')
def ftn_latest():
    score, confidence, sources = compute_daily_ftn()
    if score is None:
        return jsonify({"error": "No data available"}), 500
    prev = list(score_history)
    change = round(score - prev[-2], 1) if len(prev) > 1 else 0
    raw_score = prev[-1] if prev else score
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    return jsonify({
        "index": "F-Tone (FTN)",
        "score": score,
        "raw_score": raw_score,
        "change": change,
        "confidence": confidence,
        "sources": sources,
        "timestamp": ts
    })

@app.route('/')
def home():
    return "F-Tone (FTN) Federal Reserve Tone Index is live. Use /api/ftn_latest"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
