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
last_alerted_raw_score = None
last_alert_data = None          # stored for /send_alert manual re‑send

# ---------- FOMC SCHEDULE 2026 ----------
FOMC_DATES = [
    "2026-01-29", "2026-03-19", "2026-05-07", "2026-06-11",
    "2026-07-30", "2026-09-17", "2026-11-05", "2026-12-16"
]

def is_fomc_day():
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    return today in FOMC_DATES

def get_fomc_statement_url():
    """Return the expected FOMC statement URL for today, if today is a FOMC day."""
    today = datetime.datetime.utcnow()
    date_str = today.strftime("%Y%m%d")
    return f"https://www.federalreserve.gov/newsevents/pressreleases/monetary{date_str}a.htm"

fomc_alert_sent_today = False

# ---------- HELPERS ----------
def fetch_soup(url, timeout=10):
    r = requests.get(url, timeout=timeout)
    return BeautifulSoup(r.text, 'html.parser')

def extract_text(soup, max_chars=4000):
    for selector in ['article', 'div#content', 'body']:
        if selector == 'div#content':
            tag = soup.find('div', id='content')
        else:
            tag = soup.select_one(selector)
        if tag:
            return tag.get_text()[:max_chars]
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
        soup = fetch_soup(archive_url)
        items = soup.select('a[href*="/speech/"]')
        sources = []
        for a in items[:3]:
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
    sources = []
    if is_fomc_day():
        statement_url = get_fomc_statement_url()
        try:
            r = requests.get(statement_url, timeout=10)
            if r.status_code == 200:
                sources.append({
                    'type': 'fomc_statement',
                    'title': 'FOMC Statement',
                    'url': statement_url
                })
                logging.info(f"FOMC statement fetched directly: {statement_url}")
        except Exception as e:
            logging.warning(f"Direct FOMC statement fetch failed: {e}")

    try:
        main_soup = fetch_soup("https://www.federalreserve.gov/newsevents/pressreleases.htm")
        archive_url = get_current_year_archive(main_soup,
                                               "https://www.federalreserve.gov/newsevents/pressreleases.htm",
                                               "-press")
        soup = fetch_soup(archive_url)
        items = soup.select('a[href*="/pressrelease"]')
        for a in items[:2]:
            href = a.get('href')
            if href:
                full_url = "https://www.federalreserve.gov" + href if href.startswith('/') else href
                if looks_like_individual_doc(full_url) and not any(s['url'] == full_url for s in sources):
                    title = a.get_text(strip=True) or "FOMC Statement"
                    sources.append({'type': 'fomc_statement', 'title': title, 'url': full_url})
        logging.info(f"Scraped {len(sources)} FOMC statement links (total)")
    except Exception as e:
        logging.error(f"FOMC statements scrape error: {e}")

    return sources[:2]

def scrape_fomc_minutes():
    try:
        main_soup = fetch_soup("https://www.federalreserve.gov/monetarypolicy/fomcminutes.htm")
        archive_url = get_current_year_archive(main_soup,
                                               "https://www.federalreserve.gov/monetarypolicy/fomcminutes.htm",
                                               "fomcminutes")
        soup = fetch_soup(archive_url)
        items = soup.select('a[href*="fomcminutes"]')
        sources = []
        for a in items[:1]:
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

# ---------- FOMC SUMMARY ----------
def summarise_text(text):
    """Return a one‑sentence summary of the given Fed communication in present tense."""
    if not text or not groq_client:
        return ""
    prompt = f"Summarise the following Federal Reserve communication in one sentence using present tense. Return ONLY the sentence, no preamble.\n\n{text[:3000]}"
    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.3,
            max_tokens=80
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        logging.warning(f"Summary generation failed: {e}")
        return ""

# ---------- COMBINED PIPELINE ----------
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

    raw = sum(scores) / len(scores)
    if len(score_history) > 0:
        smoothed = round(sum(score_history) / len(score_history), 1)
    else:
        smoothed = round(raw, 1)
    score_history.append(raw)

    num_sources = len(sources_detail)
    if num_sources >= 4 and total_chars > 8000:
        confidence = "HIGH"
    elif num_sources >= 2 and total_chars > 3000:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return smoothed, confidence, sources_detail

# ---------- ALERT VALIDATION ----------
def validate_alert(is_fomc, diff, current_raw, sources, summary):
    """
    Returns True if the alert should be sent to journalists.
    Returns False if the alert is likely noise and should only go to you.
    """
    if is_fomc:
        # Must have at least one FOMC statement in sources
        has_statement = any('fomc' in s.get('type', '').lower() or 'statement' in s.get('type', '').lower() for s in sources)
        # Must have a non‑empty summary (meaning we actually scraped and summarised the statement)
        has_summary = bool(summary and summary.strip())
        # Raw score must be > 0 (not an empty pipeline)
        has_score = current_raw > 0
        return has_statement and has_summary and has_score
    else:
        # Regular alert: must be a genuine ≥ 5‑point move
        if diff < 5:
            return False
        # At least 3 sources to avoid single‑document noise
        if len(sources) < 3:
            return False
        # Confidence must not be LOW
        num_sources = len(sources)
        total_chars = sum(s.get('chars', 0) for s in sources)
        confidence = "LOW"
        if num_sources >= 4 and total_chars > 8000:
            confidence = "HIGH"
        elif num_sources >= 2 and total_chars > 3000:
            confidence = "MEDIUM"
        if confidence == "LOW":
            return False
        return True

# ---------- ALERT SENDING HELPERS ----------
def send_alert(current_raw, last_raw, diff, direction, summary="", use_journalist_list=False, blocked=False):
    global last_alert_data
    resend_api_key = os.environ.get("RESEND_API_KEY")
    if not resend_api_key:
        logging.warning("RESEND_API_KEY not set – alert skipped")
        return

    if use_journalist_list:
        alert_emails = os.environ.get("ALERT_EMAILS_2", "")
    else:
        alert_emails = os.environ.get("ALERT_EMAILS", "")

    if not alert_emails:
        logging.warning("No alert emails configured")
        return

    resend.api_key = resend_api_key
    recipients = [e.strip() for e in alert_emails.split(",") if e.strip()]
    if not recipients:
        logging.warning("No valid recipients in alert list")
        return

    subject = f"FTN Alert: Index moved {direction} by {diff:.1f} points"
    if blocked:
        subject = f"[BLOCKED] {subject}"

    body = f"""FTN Index has moved significantly.

Previous raw score: {last_raw:.1f}
Current raw score:  {current_raw:.1f}
Change: {direction} by {diff:.1f} points"""
    if summary:
        body += f"\n\nFOMC statement summary: {summary}"
    if blocked:
        body += "\n\n⚠️ This alert was automatically blocked from being sent to journalists because it did not pass validation checks. It is only sent to you for review."
    body += f"""

Live dashboard: https://ftone-index.github.io/ftone-dashboard/
Raw API: https://ftn-index.onrender.com/api/ftn_latest

This is an automated alert. Unsubscribe by replying to this email."""

    try:
        for email in recipients:
            resend.Emails.send({
                "from": "FTN Alerts <alerts@ftoneindex.com>",
                "to": email,
                "subject": subject,
                "text": body
            })
        logging.info(f"Alert email sent to {len(recipients)} recipients (journalist list: {use_journalist_list}, blocked: {blocked})")
        # Store for possible manual re‑send via /send_alert
        last_alert_data = {
            "current_raw": current_raw,
            "last_raw": last_raw,
            "diff": diff,
            "direction": direction,
            "summary": summary
        }
    except Exception as e:
        logging.error(f"Failed to send alert email: {e}")

# ---------- ROUTES ----------
@app.route('/health')
def health():
    return "OK"

@app.route('/ping')
def ping():
    global last_alerted_raw_score, fomc_alert_sent_today
    score, confidence, sources = compute_daily_ftn()
    if score is None:
        return jsonify({"status": "error", "message": "No data"}), 500

    current_raw = list(score_history)[-1] if score_history else None
    if current_raw is None:
        return jsonify({"status": "ok", "score": score, "timestamp": datetime.datetime.utcnow().isoformat() + "Z"})

    if last_alerted_raw_score is not None:
        diff = abs(current_raw - last_alerted_raw_score)
        direction = "higher" if current_raw > last_alerted_raw_score else "lower"

        now_utc = datetime.datetime.utcnow()
        if now_utc.hour == 0 and now_utc.minute < 10:
            fomc_alert_sent_today = False

        fomc_active = is_fomc_day() and now_utc.hour >= 18 and not fomc_alert_sent_today

        # Determine if this is an alert situation
        alert_triggered = False
        is_fomc_alert = False
        if fomc_active and current_raw > 0:
            is_fomc_alert = True
            alert_triggered = True
        elif diff >= 5:
            alert_triggered = True

        if alert_triggered:
            # Generate FOMC summary if applicable
            summary = ""
            if is_fomc_alert:
                fomc_text = " ".join([s['title'] + ". " + extract_text(fetch_soup(s['url']), max_chars=2000) for s in sources if 'fomc' in s.get('type', '').lower() or 'statement' in s.get('type', '').lower()])
                summary = summarise_text(fomc_text) if fomc_text else ""

            # Validate the alert
            valid = validate_alert(is_fomc_alert, diff, current_raw, sources, summary)

            if valid:
                # Send to journalists (ALERT_EMAILS_2) and you (ALERT_EMAILS)
                send_alert(current_raw, last_alerted_raw_score, diff, direction, summary, use_journalist_list=True, blocked=False)
                # Also send a copy to yourself via ALERT_EMAILS for confirmation
                send_alert(current_raw, last_alerted_raw_score, diff, direction, summary, use_journalist_list=False, blocked=False)
                if is_fomc_alert:
                    fomc_alert_sent_today = True
            else:
                # Blocked: send only to you with a warning
                send_alert(current_raw, last_alerted_raw_score, diff, direction, summary, use_journalist_list=False, blocked=True)

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

# ---------- RE‑SEND LAST ALERT TO JOURNALIST LIST (manual override) ----------
@app.route('/send_alert')
def resend_alert():
    global last_alert_data
    if not last_alert_data:
        return jsonify({"status": "No alert data to re‑send"}), 400
    send_alert(
        last_alert_data["current_raw"],
        last_alert_data["last_raw"],
        last_alert_data["diff"],
        last_alert_data["direction"],
        last_alert_data["summary"],
        use_journalist_list=True,
        blocked=False
    )
    return jsonify({"status": "Alert re‑sent to journalist list"})

# ---------- X AUTO‑POST ENDPOINT ----------
@app.route('/post_tweet')
def auto_post():
    try:
        score, confidence, sources = compute_daily_ftn()
        if score is None:
            return jsonify({"status": "No score available"})
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
        return jsonify({"status": "Tweet posted successfully"})
    except Exception as e:
        logging.error(f"Auto‑post failed: {e}")
        return jsonify({"status": f"Error posting tweet: {e}"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
