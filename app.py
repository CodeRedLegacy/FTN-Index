import requests
from bs4 import BeautifulSoup
import os
from flask import Flask, jsonify
from flask_cors import CORS
import datetime
from collections import deque
import re
import logging
from groq import Groq
import google.generativeai as genai

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

# Primary AI client (Groq)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Gemini fallback keys
GEMINI_KEY_1 = os.environ.get("GEMINI_API_KEY_1")
GEMINI_KEY_2 = os.environ.get("GEMINI_API_KEY_2")

score_history = deque(maxlen=7)

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

def scrape_fed_speeches():
    try:
        soup = fetch_soup("https://www.federalreserve.gov/newsevents/speeches.htm")
        items = soup.select('a[href*="speech"]')
        sources = []
        for a in items[:3]:
            href = a.get('href')
            if href:
                full_url = "https://www.federalreserve.gov" + href if href.startswith('/') else href
                if full_url.endswith('.xml'):
                    continue
                title = a.get_text(strip=True)
                sources.append({'type': 'speech', 'title': title, 'url': full_url})
        logging.info(f"Scraped {len(sources)} speech links")
        return sources
    except Exception as e:
        logging.error(f"Speeches scrape error: {e}")
        return []

def scrape_fomc_statements():
    try:
        soup = fetch_soup("https://www.federalreserve.gov/newsevents/pressreleases.htm")
        items = soup.select('a[href*="pressrelease"]')
        sources = []
        for a in items[:2]:
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

def scrape_fomc_minutes():
    try:
        soup = fetch_soup("https://www.federalreserve.gov/monetarypolicy/fomcminutes.htm")
        items = soup.select('a[href*="fomcminutes"]')
        sources = []
        for a in items[:1]:
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

def score_text_with_ai(text):
    if not text:
        return None
    prompt = f"""
You are a Federal Reserve communication analyzer. Rate the following text on a scale from 0 (extremely dovish, suggesting rate cuts/easing) to 100 (extremely hawkish, suggesting rate hikes/tightening). Return ONLY the number, no explanation.

Text:
{text[:3000]}
"""
    # ---------- Tier 1: Groq ----------
    try:
        chat_completion = client.chat.completions.create(
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

    # ---------- Tier 2: Gemini Key 1 ----------
    if GEMINI_KEY_1:
        try:
            genai.configure(api_key=GEMINI_KEY_1)
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(
                prompt,
                generation_config={"temperature": 0, "max_output_tokens": 5}
            )
            score_str = response.text.strip()
            digits = re.findall(r'\d+', score_str)
            if digits:
                score = int(digits[0])
                logging.info(f"AI score (Gemini-1): {score}")
                return max(0, min(100, score))
        except Exception as e:
            logging.warning(f"Gemini-1 failed ({e}), falling back to Gemini-2...")

    # ---------- Tier 3: Gemini Key 2 ----------
    if GEMINI_KEY_2:
        try:
            genai.configure(api_key=GEMINI_KEY_2)
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(
                prompt,
                generation_config={"temperature": 0, "max_output_tokens": 5}
            )
            score_str = response.text.strip()
            digits = re.findall(r'\d+', score_str)
            if digits:
                score = int(digits[0])
                logging.info(f"AI score (Gemini-2): {score}")
                return max(0, min(100, score))
        except Exception as e:
            logging.error(f"All AI providers failed: {e}")
            return None

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

@app.route('/health')
def health():
    return "OK"

@app.route('/ping')
def ping():
    score, confidence, sources = compute_daily_ftn()
    if score is None:
        return jsonify({"status": "error", "message": "No data"}), 500
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    return jsonify({
        "status": "ok",
        "score": score,
        "timestamp": ts
    })

@app.route('/api/ftn_latest')
def ftn_latest():
    score, confidence, sources = compute_daily_ftn()
    if score is None:
        return jsonify({"error": "No data available"}), 500

    prev = list(score_history)
    change = round(score - prev[-2], 1) if len(prev) > 1 else 0

    # Grab the most recent raw (unsmoothed) score from the history
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
