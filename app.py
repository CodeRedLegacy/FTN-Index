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
CORS(app)  # Allow all origins (your GitHub Pages dashboard)
logging.basicConfig(level=logging.INFO)

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

score_history = deque(maxlen=7)

def scrape_fed_speeches():
    try:
        url = "https://www.federalreserve.gov/newsevents/speeches.htm"
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        speeches = []
        for item in soup.select('a[href*="speech"]'):
            href = item.get('href')
            if href:
                full_url = "https://www.federalreserve.gov" + href if href.startswith('/') else href
                speeches.append(full_url)
        logging.info(f"Scraped {len(speeches)} speech links")
        return speeches[:3]
    except Exception as e:
        logging.error(f"Scrape error: {e}")
        return []

def extract_text_from_speech(url):
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        article = soup.find('article')
        if article:
            text = article.get_text()
            logging.info(f"Extracted {len(text)} chars via <article> from {url[:60]}")
            return text[:4000]
        content_div = soup.find('div', id='content')
        if content_div:
            text = content_div.get_text()
            logging.info(f"Extracted {len(text)} chars via #content from {url[:60]}")
            return text[:4000]
        body = soup.find('body')
        if body:
            text = body.get_text()
            logging.info(f"Extracted {len(text)} chars via <body> from {url[:60]}")
            return text[:4000]
        logging.warning(f"No text container found on {url}")
        return ""
    except Exception as e:
        logging.error(f"Extract error: {e}")
        return ""

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
            config={
                "temperature": 0,
                "max_output_tokens": 5,
            }
        )
        score_str = response.text.strip()
        digits = re.findall(r'\d+', score_str)
        if digits:
            score = int(digits[0])
            logging.info(f"AI score: {score}")
            return max(0, min(100, score))
        else:
            logging.warning(f"No digits in AI response: {score_str}")
    except Exception as e:
        logging.error(f"Gemini API error: {e}")
    return None

def compute_daily_ftn():
    speeches = scrape_fed_speeches()
    if not speeches:
        return None
    scores = []
    for sp in speeches:
        text = extract_text_from_speech(sp)
        if text:
            score = score_text_with_ai(text)
            if score is not None:
                scores.append(score)
    if not scores:
        return None
    raw = sum(scores) / len(scores)
    score_history.append(raw)
    smoothed = sum(score_history) / len(score_history)
    return round(smoothed, 1)

@app.route('/api/ftn_latest')
def ftn_latest():
    score = compute_daily_ftn()
    if score is None:
        return jsonify({"error": "No data available"}), 500
    prev_scores = list(score_history)
    change = 0
    if len(prev_scores) > 1:
        change = round(score - prev_scores[-2], 1)
    return jsonify({
        "index": "F-Tone (FTN)",
        "score": score,
        "change": change,
        "timestamp": datetime.datetime.utcnow().isoformat()
    })

@app.route('/')
def home():
    return "F-Tone (FTN) Federal Reserve Tone Index is live. Use /api/ftn_latest"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
