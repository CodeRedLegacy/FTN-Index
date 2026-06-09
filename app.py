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

# Try primary Groq key first, fall back to secondary
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_API_KEY_2 = os.environ.get("GROQ_API_KEY_2")

groq_client = None
if GROQ_API_KEY and GROQ_API_KEY.strip():
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
        logging.info("Groq client initialized with primary key")
    except Exception as e:
        logging.warning(f"Failed to initialize Groq with primary key: {e}")
elif GROQ_API_KEY_2 and GROQ_API_KEY_2.strip():
    try:
        groq_client = Groq(api_key=GROQ_API_KEY_2)
        logging.info("Groq client initialized with secondary key")
    except Exception as e:
        logging.warning(f"Failed to initialize Groq with secondary key: {e}")
else:
    logging.warning("No valid GROQ_API_KEY found; Groq will be skipped.")

from google import genai
GEMINI_KEY_1 = os.environ.get("GEMINI_API_KEY_1")
GEMINI_KEY_2 = os.environ.get("GEMINI_API_KEY_2")
GEMINI_KEY_3 = os.environ.get("GEMINI_API_KEY_3")

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

score_history = deque(maxlen=7)

# ---------- MOVING ALERT STATE ----------
last_alerted_raw_score = None

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

# ---------- SOURCE SCRAPERS ----------
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

def scrape_regional_fed_speeches():
    try:
        soup = fetch_soup("https://www.newyorkfed.org/newsevents/speeches")
        items = soup.select('a[href*="speech"]')
        sources = []
        for a in items[:2]:
            href = a.get('href')
            if href:
                full_url = "https://www.newyorkfed.org" + href if href.startswith('/') else href
                title = a.get_text(strip=True) or "Regional Fed Speech"
                if not any(s['url'] == full_url for s in sources):
                    sources.append({'type': 'regional_speech', 'title': title, 'url': full_url})
        logging.info(f"Scraped {len(sources)} regional Fed speech links")
        return sources
    except Exception as e:
        logging.error(f"Regional Fed speeches scrape error: {e}")
        return []

def scrape_fed_testimony():
    try:
        soup = fetch_soup("https://www.federalreserve.gov/newsevents/testimony.htm")
        items = soup.select('a[href*="testimony"]')
        sources = []
        for a in items[:2]:
            href = a.get('href')
            if href:
                full_url = "https://www.federalreserve.gov" + href if href.startswith('/') else href
                if looks_like_individual_doc(full_url):
                    title = a.get_text(strip=True) or "Testimony"
                    if not any(s['url'] == full_url for s in sources):
                        sources.append({'type': 'testimony', 'title': title, 'url': full_url})
        logging.info(f"Scraped {len(sources)} testimony links")
        return sources
    except Exception as e:
        logging.error(f"Testimony scrape error: {e}")
        return []

def scrape_fed_blogs():
    try:
        soup = fetch_soup("https://libertystreeteconomics.newyorkfed.org/")
        items = soup.select('a[href*="libertystreeteconomics"]')
        sources = []
        for a in items[:2]:
            href = a.get('href')
            if href:
                full_url = href if href.startswith('http') else "https://libertystreeteconomics.newyorkfed.org" + href
                title = a.get_text(strip=True) or "Fed Blog Post"
                if not any(s['url'] == full_url for s in sources):
                    sources.append({'type': 'fed_blog', 'title': title, 'url': full_url})
        logging.info(f"Scraped {len(sources)} Fed blog links")
        return sources
    except Exception as e:
        logging.error(f"Fed blogs scrape error: {e}")
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
        logging.info("Groq client not available, skipping to Gemini...")
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

# ---------- COMBINED PIPELINE (SMOOTHING FIXED) ----------
def compute_daily_ftn():
    all_sources = []
    all_sources.extend(scrape_fed_speeches())
    all_sources.extend(scrape_fomc_statements())
    all_sources.extend(scrape_fomc_minutes())
    all_sources.extend(scrape_regional_fed_speeches())
    all_sources.extend(scrape_fed_testimony())
    all_sources.extend(scrape_fed_blogs())
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

    # --- Compute today's raw score (before adding to history) ---
    raw = sum(scores) / len(scores)

    # --- Smoothed score = average of PAST scores only (excludes today) ---
    if len(score_history) > 0:
        smoothed = round(sum(score_history) / len(score_history), 1)
    else:
        smoothed = round(raw, 1)   # First day: smoothed = raw

    # --- Now add today's raw to history for FUTURE smoothing ---
    score_history.append(raw)

    # --- Confidence ---
    num_sources = len(sources_detail)
    if num_sources >= 4 and total_chars > 8000:
        confidence = "HIGH"
    elif num_sources >= 2 and total_chars > 3000:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return smoothed, confidence, sources_detail

# ---------- MARKET EXPECTATION ENDPOINT (Solution B, final) ----------
def compute_market_ftn():
    """
    Returns a 0‑100 score representing what the market is pricing in
    about the Fed's next moves, derived from:
      - 2‑year Treasury yield (rate hike/cut expectations)
      - 2y/10y Treasury spread (yield curve)
      - US Dollar Index (DXY) intraday change
    """
    y2 = None
    y10 = None
    spread = 0
    dxy_change = 0

    fred_api_key = os.environ.get("FRED_API_KEY")
    if fred_api_key:
        try:
            # 2‑year yield
            resp_2y = requests.get(
                f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS2&api_key={fred_api_key}&file_type=json&sort_order=desc&limit=1",
                timeout=15
            )
            if resp_2y.status_code == 200:
                obs = resp_2y.json().get("observations", [])
                if obs:
                    y2 = float(obs[0].get("value", 0) or 0)

            # 10‑year yield
            resp_10y = requests.get(
                f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key={fred_api_key}&file_type=json&sort_order=desc&limit=1",
                timeout=15
            )
            if resp_10y.status_code == 200:
                obs = resp_10y.json().get("observations", [])
                if obs:
                    y10 = float(obs[0].get("value", 0) or 0)

            if y2 is not None and y10 is not None:
                spread = y10 - y2
        except Exception as e:
            logging.warning(f"FRED error: {e}")

    # 2‑year yield as rate‑hike expectation
    # Map a plausible range (3%–6%) to 0–100
    if y2 is not None and y2 > 0:
        hike_score = min(100, max(0, (y2 - 3.0) * (100 / 3.0)))
    else:
        hike_score = 50   # neutral default

    # Spread score: -1 to +1 → 0 to 100
    spread_score = min(100, max(0, 50 + spread * 50))

    # DXY intraday change
    try:
        dxy_url = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1d&range=1d"
        dxy_resp = requests.get(dxy_url, timeout=15)
        if dxy_resp.status_code == 200:
            dxy_json = dxy_resp.json()
            result = dxy_json.get("chart", {}).get("result", [])
            if result:
                meta = result[0].get("meta", {})
                # Try quote indicators first (open/close)
                indicators = result[0].get("indicators", {}).get("quote", [{}])
                if indicators and indicators[0]:
                    opens = indicators[0].get("open", [])
                    closes = indicators[0].get("close", [])
                    if opens and closes and opens[0] and closes[0]:
                        open_val = float(opens[0])
                        close_val = float(closes[0])
                        if open_val and close_val:
                            dxy_change = ((close_val / open_val) - 1) * 100
                # Fallback to meta previousClose
                if dxy_change == 0:
                    prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
                    current = meta.get("regularMarketPrice")
                    if prev_close and current:
                        dxy_change = ((current / prev_close) - 1) * 100
    except Exception as e:
        logging.warning(f"DXY error: {e}")

    # DXY score: -0.5% to +0.5% → 0 to 100
    dxy_score = min(100, max(0, 50 + dxy_change * 100))

    # Average the three components
    market_ftn = round((hike_score + spread_score + dxy_score) / 3, 1)

    # Label
    if market_ftn <= 20:
        label = "Extremely Dovish"
    elif market_ftn <= 40:
        label = "Dovish"
    elif market_ftn <= 60:
        label = "Neutral"
    elif market_ftn <= 80:
        label = "Hawkish"
    else:
        label = "Extremely Hawkish"

    return market_ftn, label, {
        "y2": y2,
        "spread": spread,
        "dxy_change": dxy_change,
        "hike_score": hike_score,
        "spread_score": spread_score,
        "dxy_score": dxy_score
    }

@app.route('/api/market_ftn')
def market_ftn():
    score, label, components = compute_market_ftn()
    if score is None:
        return jsonify({"error": "Market data unavailable"}), 500
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    return jsonify({
        "index": "Market Expectation (FTN‑M)",
        "score": score,
        "label": label,
        "components": components,
        "timestamp": ts
    })

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
    current_raw = list(score_history)[-1] if score_history else None
    if current_raw is not None and last_alerted_raw_score is not None:
        diff = abs(current_raw - last_alerted_raw_score)
        if diff >= 5:
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
                            "from": "FTN Alerts <alerts@ftoneindex.com>",
                            "to": email,
                            "subject": subject,
                            "text": body
                        })
                    logging.info(f"Alert email sent to {len(recipients)} recipients")
                except Exception as e:
                    logging.error(f"Failed to send alert email: {e}")
            else:
                logging.warning("RESEND_API_KEY or ALERT_EMAILS not set – alert skipped")
        last_alerted_raw_score = current_raw
    elif last_alerted_raw_score is None and current_raw is not None:
        last_alerted_raw_score = current_raw
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
