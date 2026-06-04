import requests
from bs4 import BeautifulSoup
import os
from flask import Flask, jsonify
from flask_cors import CORS
import datetime
from collections import deque
import re
import logging
import tweepy
import resend

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

# ---------- MOVING ALERT STATE ----------
last_alerted_raw_score = None   # Prevent duplicate alerts for the same move

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

def get_current_year_archive(main_soup, base_url, keyword):
    current_year = str(datetime.datetime.utcnow().year)
    for a in main_soup.select('a[href]'):
        href = a.get('href')
        if href and keyword in href and current_year in href:
            full_url = "https://www.federalreserve.gov" + href if href.startswith('/') else href
            return full_url
    return base_url

def looks_like_individual_doc(url):
    if any(kw in url for kw in ['foia', 'rss', '.xml', 'speeches.htm', 'pressreleases.htm', 'fomcminutes.htm']):
        return False
    if re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', url, re.IGNORECASE):
        return True
    if re.search(r'\d{8}', url):
        return True
    if re.search(r'\d{4,}[a-z]\.htm', url, re.IGNORECASE):
        return True
    return False

def extract_speaker_from_url(url):
    m = re.search(r'/([a-z]+?)\d{8,}a?\.htm', url, re.IGNORECASE)
    if m:
        name = m.group(1).capitalize()
        known = {
            'Powell': 'Powell', 'Bowman': 'Bowman', 'Jefferson': 'Jefferson',
            'Waller': 'Waller', 'Warsh': 'Warsh', 'Brainard': 'Brainard',
            'Clarida': 'Clarida', 'Quarles': 'Quarles', 'Logan': 'Logan',
            'Mester': 'Mester', 'Williams': 'Williams', 'Bostic': 'Bostic',
            'Harker': 'Harker', 'Kashkari': 'Kashkari', 'George': 'George',
            'Bullard': 'Bullard', 'Evans': 'Evans', 'Rosengren': 'Rosengren',
            'Kaplan': 'Kaplan', 'Daly': 'Daly', 'Barkin': 'Barkin',
        }
        return known.get(name, name)
    return 'Fed'

# ---------- SOURCE SCRAPERS (TWO-STEP) ----------
def scrape_fed_speeches():
    try:
        main_soup = fetch_soup("https://www.federalreserve.gov/newsevents/speeches.htm")
        archive_url = get_current_year_archive(main_soup,
                                               "https://www.federalreserve.gov/newsevents/speeches.htm",
                                               "-speeches")
        logging.info(f"Using speech archive: {archive_url}")
        soup = fetch_soup(archive_url)
        items = soup.select('a[href*="/speech/"]')
        sources = []
        for a in items:
            if len(sources) >= 3:
                break
            href = a.get('href')
            if href:
                full_url = "https://www.federalreserve.gov" + href if href.startswith('/') else href
                if looks_like_individual_doc(full_url):
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
        main_soup = fetch_soup("https://www.federalreserve.gov/newsevents/pressreleases.htm")
        archive_url = get_current_year_archive(main_soup,
                                               "https://www.federalreserve.gov/newsevents/pressreleases.htm",
                                               "-press")
        logging.info(f"Using press release archive: {archive_url}")
        soup = fetch_soup(archive_url)
        items = soup.select('a[href*="/pressrelease"]')
        sources = []
        for a in items:
            if len(sources) >= 2:
                break
            href = a.get('href')
            if href:
                full_url = "https://www.federalreserve.gov" + href if href.startswith('/') else href
                if looks_like_individual_doc(full_url):
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
        main_soup = fetch_soup("https://www.federalreserve.gov/monetarypolicy/fomcminutes.htm")
        archive_url = get_current_year_archive(main_soup,
                                               "https://www.federalreserve.gov/monetarypolicy/fomcminutes.htm",
                                               "fomcminutes")
        logging.info(f"Using minutes archive: {archive_url}")
        soup = fetch_soup(archive_url)
        items = soup.select('a[href*="fomcminutes"]')
        sources = []
        for a in items:
            if len(sources) >= 1:
                break
            href = a.get('href')
            if href:
                full_url = "https://www.federalreserve.gov" + href if href.startswith('/') else href
                if looks_like_individual_doc(full_url):
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
                    speaker = extract_speaker_from_url(src['url'])
                    sources_detail.append({
                        'type': src['type'],
                        'title': src['title'],
                        'url': src['url'],
                        'chars': len(text),
                        'speaker': speaker
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
    global last_alerted_raw_score
    score, confidence, sources = compute_daily_ftn()
    if score is None:
        return jsonify({"status": "error", "message": "No data"}), 500

    # ---------- MOVING ALERT LOGIC (integrated) ----------
    current_raw = list(score_history)[-1] if score_history else None
    if current_raw is not None and last_alerted_raw_score is not None:
        diff = abs(current_raw - last_alerted_raw_score)
        if diff >= 5:
            # Attempt to send email alert
            resend_api_key = os.environ.get("RESEND_API_KEY")
            alert_emails = os.environ.get("ALERT_EMAILS", "")
            if resend_api_key and alert_emails:
                resend.api_key = resend_api_key
                recipients = [e.strip() for e in alert_emails.split(",") if e.strip()]
                direction = "higher" if current_raw > last_alerted_raw_score else "lower"
                subject = f"FTN Alert: Index moved {direction} by {diff:.1f} points"
                body = f"""FTN Index has moved significantly.

Previous raw score: {last_alerted_raw_score:.1f}
Current raw score:  {current_raw:.1f}
Change: {direction} by {diff:.1f} points

Live dashboard: https://ftone-index.github.io/ftone-dashboard/
Raw API: https://ftn-index.onrender.com/api/ftn_latest

This is an automated alert. Unsubscribe by replying to this email.
"""
                try:
                    for email in recipients:
                        resend.Emails.send({
                            "from": "FTN Alerts <alerts@ftone-index.resend.dev>",
                            "to": email,
                            "subject": subject,
                            "text": body
                        })
                    logging.info(f"Alert email sent to {len(recipients)} recipients")
                except Exception as e:
                    logging.error(f"Failed to send alert email: {e}")
            else:
                logging.warning("RESEND_API_KEY or ALERT_EMAILS not set – alert skipped")
        # Update last alerted score regardless of whether email was sent
        last_alerted_raw_score = current_raw
    elif last_alerted_raw_score is None and current_raw is not None:
        # First run – initialise without sending alert
        last_alerted_raw_score = current_raw

    ts = datetime.datetime.utcnow().isoformat() + "Z"
    return jsonify({"status": "ok", "score": score, "timestamp": ts, "alert_sent": False})   # alert_sent info not exposed

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

# ---------- X AUTO‑POST ENDPOINT ----------
def post_to_x():
    try:
        score, confidence, sources = compute_daily_ftn()
        if score is None:
            return "No score available"
        prev = list(score_history)
        change = round(score - prev[-2], 1) if len(prev) > 1 else 0
        if change == 0:
            arrow = "—"
        elif change > 0:
            arrow = f"▲{abs(change)}"
        else:
            arrow = f"▼{abs(change)}"
        if score <= 20:
            label = "Extremely Dovish"
        elif score <= 40:
            label = "Dovish"
        elif score <= 60:
            label = "Neutral"
        elif score <= 80:
            label = "Hawkish"
        else:
            label = "Extremely Hawkish"
        sources_count = len(sources) if sources else 0
        tweet_text = (
            f"🏛️ FTN today: {score} {arrow} — {label}\n"
            f"Confidence: {confidence} | Sources: {sources_count}"
        )
        client = tweepy.Client(
            consumer_key=os.environ["X_CONSUMER_KEY"],
            consumer_secret=os.environ["X_CONSUMER_SECRET"],
            access_token=os.environ["X_ACCESS_TOKEN"],
            access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"]
        )
        response = client.create_tweet(text=tweet_text)
        logging.info(f"Tweet posted: {response.data['id']}")
        return "Tweet posted successfully"
    except Exception as e:
        logging.error(f"Auto‑post failed: {e}")
        return f"Error posting tweet: {e}"

@app.route('/post_tweet')
def auto_post():
    result = post_to_x()
    return jsonify({"status": result})

# ---------- MANUAL MOVING ALERT ENDPOINT (for testing) ----------
@app.route('/moving')
def moving_alert():
    global last_alerted_raw_score
    # This endpoint is now just a manual trigger – the real alert runs inside /ping
    # We'll force a check and return the current state
    _, _, _ = compute_daily_ftn()
    current_raw = list(score_history)[-1] if score_history else None
    if current_raw is None:
        return jsonify({"status": "No data"})
    if last_alerted_raw_score is None:
        last_alerted_raw_score = current_raw
        return jsonify({"status": "Initialized", "current_raw": current_raw})
    diff = abs(current_raw - last_alerted_raw_score)
    return jsonify({
        "status": "checked",
        "current_raw": current_raw,
        "last_alerted": last_alerted_raw_score,
        "diff": diff,
        "big_move": diff >= 5
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
