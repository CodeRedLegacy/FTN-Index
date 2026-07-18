import requests
from bs4 import BeautifulSoup
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import datetime
from collections import deque
import re
import logging
import tweepy
import resend
import openai
import json
from datetime import datetime as dt

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

# ---------- ADDITIONAL AI PROVIDERS ----------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

# ---------- TRIAL KEY VALIDATION ----------
# Valid trial keys are stored as a JSON object in the VALID_TRIAL_KEYS environment variable
# Format: {"key1": "YYYY-MM-DD", "key2": "YYYY-MM-DD"}

@app.route('/api/validate_trial')
def validate_trial():
    """Validate a trial key. Returns {'valid': True/False, 'reason': '...'}"""
    key = request.args.get('key')
    if not key:
        return jsonify({"valid": False, "reason": "No key provided"}), 400

    valid_keys_json = os.environ.get("VALID_TRIAL_KEYS", "{}")
    try:
        valid_keys = json.loads(valid_keys_json)
    except json.JSONDecodeError:
        logging.error("Invalid VALID_TRIAL_KEYS format")
        return jsonify({"valid": False, "reason": "Server configuration error"}), 500

    if key not in valid_keys:
        return jsonify({"valid": False, "reason": "Invalid key"}), 200

    expiry_date_str = valid_keys[key]
    try:
        expiry_date = datetime.datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
        today = datetime.datetime.utcnow().date()
        if today > expiry_date:
            return jsonify({"valid": False, "reason": "Key expired"}), 200
        return jsonify({"valid": True, "reason": "Active"}), 200
    except ValueError:
        return jsonify({"valid": False, "reason": "Invalid expiry format"}), 500

# ---------- PROSPECT OUTREACH ----------
def generate_prospect_email(name, company):
    """Generate the prospect outreach email body."""
    return f"""
Dear {name},

I am writing to introduce you to the FTN Index — a daily, AI-powered gauge of Federal Reserve tone on a 0–100 scale, from dovish to hawkish.

The index scrapes Fed speeches, FOMC statements, and minutes, scores each document using a chain of free LLM APIs (Groq, Gemini, DeepSeek, OpenRouter), smooths the results with a 7-day moving average, and publishes the score with confidence, sources, and methodology on a public dashboard.

**What makes it different:**
- **Market Expectation** — a companion score derived from Treasury yields (2-year and 2y/10y spread) and the US Dollar Index (DXY), showing what markets are pricing in.
- **Fed policy rates** — the actual Fed Funds target range, IORB rate, and ON RRP rate, displayed alongside the sentiment score for direct comparison.
- **Radical transparency** — every score is linked to its source document.
- **FOMC alert system** — automated alerts on significant moves (fully tested and reliable).

The dashboard is live and free to explore:
https://ftone-index.github.io/ftone-dashboard/

If you are interested, I would be happy to give you a personal walkthrough or answer any questions.

Best regards,
Eduardo
@FToneIndex on X
"""

@app.route('/send_prospect_emails')
def send_prospect_emails():
    """Send outreach emails to prospects using Resend.
    Trigger this manually via browser or curl.
    Security: requires a secret key passed as a query parameter.
    """
    # Security check
    secret_key = request.args.get('key')
    expected_key = os.environ.get("OUTREACH_KEY", "secret")
    if secret_key != expected_key:
        return jsonify({"error": "Invalid or missing security key"}), 403

    # Get the prospect list from environment variable
    prospects_json = os.environ.get("PROSPECTS")
    if not prospects_json:
        return jsonify({"error": "No prospects configured"}), 500

    try:
        prospects = json.loads(prospects_json)
    except json.JSONDecodeError:
        logging.error("Invalid PROSPECTS format")
        return jsonify({"error": "Invalid prospects format"}), 500

    # Validate Resend API key
    resend_api_key = os.environ.get("RESEND_API_KEY")
    if not resend_api_key:
        return jsonify({"error": "RESEND_API_KEY not set"}), 500

    resend.api_key = resend_api_key

    # Send emails
    sent = 0
    failed = 0
    errors = []

    for prospect in prospects:
        name = prospect.get('name', '')
        email = prospect.get('email', '')
        company = prospect.get('company', '')

        if not name or not email:
            logging.warning(f"Skipping prospect: missing name or email — {prospect}")
            continue

        try:
            response = resend.Emails.send({
                "from": "FTN Index <alerts@ftoneindex.com>",
                "to": email,
                "subject": "FTN Index — real-time Fed sentiment, Market Expectation, and Fed policy rates",
                "text": generate_prospect_email(name, company)
            })
            sent += 1
            logging.info(f"Email sent to {name} ({email}) — ID: {response.get('id', 'N/A')}")
        except Exception as e:
            failed += 1
            error_msg = f"Failed to send to {email}: {e}"
            errors.append(error_msg)
            logging.error(error_msg)

    return jsonify({
        "status": "Outreach completed",
        "sent": sent,
        "failed": failed,
        "errors": errors if errors else None
    })

# ---------- HISTORICAL CSV EXPORT ----------
@app.route('/api/historical_csv')
def historical_csv():
    """Return the historical FTN CSV file if a valid trial key is provided."""
    key = request.args.get('key')
    if not key:
        return jsonify({"error": "Missing trial key"}), 400

    # Validate the key
    valid_keys_json = os.environ.get("VALID_TRIAL_KEYS", "{}")
    try:
        valid_keys = json.loads(valid_keys_json)
    except json.JSONDecodeError:
        return jsonify({"error": "Server configuration error"}), 500

    if key not in valid_keys:
        return jsonify({"error": "Invalid or expired key"}), 403

    # Fetch the CSV from GitHub
    csv_url = "https://raw.githubusercontent.com/ftone-index/ftn-history/main/ftn_log.csv"
    try:
        resp = requests.get(csv_url, timeout=10)
        if resp.status_code != 200:
            return jsonify({"error": "Could not retrieve historical data"}), 500
        
        # Return as a downloadable CSV file
        return resp.text, 200, {
            'Content-Type': 'text/csv',
            'Content-Disposition': 'attachment; filename=ftn_history.csv'
        }
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- PERSISTENT HISTORY HELPER ----------
def get_daily_average_scores(days=7):
    """
    Fetch the historical CSV from GitHub, group rows by date (YYYY-MM-DD),
    compute the daily average of raw scores, and return the last 'days' daily averages
    as a list of floats (oldest first).
    """
    csv_url = "https://raw.githubusercontent.com/ftone-index/ftn-history/main/ftn_log.csv"
    try:
        resp = requests.get(csv_url, timeout=10)
        if resp.status_code != 200:
            logging.warning("Could not fetch CSV for historical smoothing")
            return []
        
        lines = resp.text.strip().split('\n')
        if not lines:
            return []
        
        # Skip header if present
        if 'timestamp' in lines[0].lower():
            lines = lines[1:]
        
        # Group raw scores by date (YYYY-MM-DD)
        daily_scores = {}
        for line in lines:
            parts = line.split(',')
            if len(parts) < 3:
                continue
            try:
                ts = parts[0].strip()
                # raw_score is at index 2; fallback to score at index 1
                raw_str = parts[2].strip() if len(parts) > 2 and parts[2].strip() else parts[1].strip()
                raw = float(raw_str)
                date_key = ts[:10]  # YYYY-MM-DD
                if date_key not in daily_scores:
                    daily_scores[date_key] = []
                daily_scores[date_key].append(raw)
            except (ValueError, IndexError) as e:
                logging.warning(f"Skipping malformed CSV line: {line[:50]}...")
                continue
        
        # Sort dates and compute daily averages
        sorted_dates = sorted(daily_scores.keys())
        daily_avgs = []
        for d in sorted_dates:
            day_scores = daily_scores[d]
            if day_scores:
                daily_avgs.append(sum(day_scores) / len(day_scores))
        
        # Return the last 'days' daily averages (or all if fewer)
        return daily_avgs[-days:] if daily_avgs else []
    
    except Exception as e:
        logging.error(f"Failed to fetch historical scores: {e}")
        return []

# ---------- FOMC SCHEDULE 2026 ----------
FOMC_DATES = [
    "2026-01-29", "2026-03-19", "2026-05-07", "2026-06-11",
    "2026-07-30", "2026-09-17", "2026-11-05", "2026-12-16"
]

def is_fomc_day():
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    return today in FOMC_DATES

def get_fomc_statement_url():
    today = datetime.datetime.utcnow()
    date_str = today.strftime("%Y%m%d")
    return f"https://www.federalreserve.gov/newsevents/pressreleases/monetary{date_str}a.htm"

fomc_alert_sent_today = False

# ---------- HELPERS ----------
def fetch_soup(url, timeout=10):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    r = requests.get(url, timeout=timeout, headers=headers)
    return BeautifulSoup(r.text, 'html.parser')

def extract_text(soup, max_chars=4000):
    # Try common content containers
    for selector in ['article', 'div#content', 'div.content', 'main', 'div.article-body', 'div.story-body']:
        tag = soup.select_one(selector)
        if tag:
            text = tag.get_text(separator=' ', strip=True)
            if len(text) > 100:
                return text[:max_chars]
    # Fallback: get all paragraph text
    paragraphs = soup.find_all('p')
    if paragraphs:
        text = ' '.join([p.get_text(strip=True) for p in paragraphs])
        if len(text) > 100:
            return text[:max_chars]
    # Ultimate fallback: just get the body text
    body = soup.find('body')
    if body:
        return body.get_text(separator=' ', strip=True)[:max_chars]
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
            logging.warning(f"Gemini-3 failed ({e}), falling back to DeepSeek...")
    
    # Tier 5: DeepSeek
    if DEEPSEEK_API_KEY and DEEPSEEK_API_KEY.strip():
        try:
            deepseek_client = openai.OpenAI(
                api_key=DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com/v1"
            )
            response = deepseek_client.chat.completions.create(
                model="deepseek-v4-flash",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=5
            )
            score_str = response.choices[0].message.content.strip()
            digits = re.findall(r'\d+', score_str)
            if digits:
                score = int(digits[0])
                logging.info(f"AI score (DeepSeek): {score}")
                return max(0, min(100, score))
        except Exception as e:
            logging.warning(f"DeepSeek failed ({e}), falling back to OpenRouter...")
    
    # Tier 6: OpenRouter
    if OPENROUTER_API_KEY and OPENROUTER_API_KEY.strip():
        try:
            openrouter_client = openai.OpenAI(
                api_key=OPENROUTER_API_KEY,
                base_url=OPENROUTER_BASE_URL
            )
            response = openrouter_client.chat.completions.create(
                model="openai/gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=5
            )
            score_str = response.choices[0].message.content.strip()
            digits = re.findall(r'\d+', score_str)
            if digits:
                score = int(digits[0])
                logging.info(f"AI score (OpenRouter): {score}")
                return max(0, min(100, score))
        except Exception as e:
            logging.error(f"OpenRouter failed ({e})")
            return None

    # If we've made it here, all AI providers have failed
    logging.error("All AI providers failed (Groq, Gemini 1-3, DeepSeek, OpenRouter)")
    return None

# ---------- FOMC SUMMARY ----------
def summarise_text(text, score, previous_score=None):
    if not text or not groq_client:
        return ""
    
    # Calculate change if previous score is provided
    change_str = ""
    if previous_score is not None:
        diff = score - previous_score
        if abs(diff) >= 0.5:
            direction = "higher" if diff > 0 else "lower"
            change_str = f"moved {abs(diff):.1f} points {direction} to {score:.1f}"
        else:
            change_str = f"is at {score:.1f}, broadly unchanged"
    else:
        change_str = f"is at {score:.1f}"
    
    prompt = f"""
Summarise the following Federal Reserve communication in three concise sentences.

First sentence: summarise the key policy decision and tone.
Second sentence: state where the FTN Index stands (it {change_str}) and what this reflects.
Third sentence: state one or two key implications for markets, based on the text and the context.

Keep the total response under 100 words. Return ONLY these three sentences, no preamble.

Text:
{text[:3000]}
"""
    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.3,
            max_tokens=120
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
        return None, None, [], None

    raw = sum(scores) / len(scores)
    
    # Get daily averages from CSV history
    daily_avgs = get_daily_average_scores(days=7)
    
    # If we have at least 7 days of history, use the average of the last 7 daily averages
    if len(daily_avgs) >= 7:
        smoothed = round(sum(daily_avgs) / len(daily_avgs), 1)
    else:
        # Not enough history yet – fallback to raw
        smoothed = round(raw, 1)

    num_sources = len(sources_detail)
    if num_sources >= 4 and total_chars > 8000:
        confidence = "HIGH"
    elif num_sources >= 2 and total_chars > 3000:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return smoothed, confidence, sources_detail, raw

# ---------- ALERT VALIDATION ----------
def validate_alert(is_fomc, diff, current_raw, sources, summary):
    if is_fomc:
        has_statement = any('fomc' in s.get('type', '').lower() or 'statement' in s.get('type', '').lower() for s in sources)
        has_summary = bool(summary and summary.strip())
        has_score = current_raw > 0
        return has_statement and has_summary and has_score
    else:
        if diff < 5:
            return False
        if len(sources) < 3:
            return False
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
def send_alert(current_raw, last_raw, diff, direction, summary="", use_journalist_list=False, blocked=False, alert_type="move"):
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

    # --- Customise subject and body based on alert type ---
    if alert_type == "fomc":
        subject = f"FTN Alert: FOMC Statement Released – Score {current_raw:.1f}"
        body = f"""FTN Index – FOMC Statement Alert.

Current FTN score: {current_raw:.1f}"""
        if summary:
            body += f"\n\n{summary}"
        body += f"""

Live dashboard: https://ftone-index.github.io/ftone-dashboard/
Raw API: https://ftn-index.onrender.com/api/ftn_latest

This is an automated alert. Unsubscribe by replying to this email."""
    else:
        # Standard 5‑point move alert
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
        logging.info(f"Alert email sent to {len(recipients)} recipients (journalist list: {use_journalist_list}, blocked: {blocked}, type: {alert_type})")
        last_alert_data = {
            "current_raw": current_raw,
            "last_raw": last_raw,
            "diff": diff,
            "direction": direction,
            "summary": summary
        }
    except Exception as e:
        logging.error(f"Failed to send alert email: {e}")
last_alert_data = None

# ---------- ROUTES ----------
@app.route('/health')
def health():
    return "OK"

@app.route('/ping')
def ping():
    global last_alerted_raw_score, fomc_alert_sent_today
    result = compute_daily_ftn()
    if result[0] is None:
        return jsonify({"status": "error", "message": "No data"}), 500
    score, confidence, sources, current_raw = result

    now_utc = datetime.datetime.utcnow()
    if now_utc.hour == 0 and now_utc.minute < 10:
        fomc_alert_sent_today = False

    fomc_active = is_fomc_day() and now_utc.hour >= 18 and not fomc_alert_sent_today

    # --- FOMC Alert (Independent of last_alerted_raw_score) ---
    if fomc_active and current_raw > 0:
        try:
            fomc_text = " ".join([
                s['title'] + ". " + extract_text(fetch_soup(s['url']), max_chars=2000)
                for s in sources
                if 'fomc' in s.get('type', '').lower() or 'statement' in s.get('type', '').lower()
            ])
            # Send to journalists (ALERT_EMAILS_2)
            send_alert(
                current_raw,
                current_raw,
                0,
                "unchanged",
                summary,
                use_journalist_list=True,
                blocked=False,
                alert_type="fomc"
            )
            # Send to yourself (ALERT_EMAILS)
            send_alert(
                current_raw,
                current_raw,
                0,
                "unchanged",
                summary,
                use_journalist_list=False,
                blocked=False,
                alert_type="fomc"
            )
            fomc_alert_sent_today = True
            logging.info(f"FOMC alert sent for score {current_raw}")
        except Exception as e:
            logging.error(f"FOMC alert failed: {e}")
            
    # --- 5-Point Move Alert (Requires previous score) ---
    if last_alerted_raw_score is not None:
        diff = abs(current_raw - last_alerted_raw_score)
        direction = "higher" if current_raw > last_alerted_raw_score else "lower"

        if diff >= 5 and not fomc_active:
            # Send to journalists (ALERT_EMAILS_2)
            send_alert(
                current_raw,
                last_alerted_raw_score,
                diff,
                direction,
                "",
                use_journalist_list=True,
                blocked=False,
                alert_type="move"
            )
            # Send to yourself (ALERT_EMAILS)
            send_alert(
                current_raw,
                last_alerted_raw_score,
                diff,
                direction,
                "",
                use_journalist_list=False,
                blocked=False,
                alert_type="move"
            )

    last_alerted_raw_score = current_raw
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    return jsonify({"status": "ok", "score": score, "timestamp": ts})

last_alerted_raw_score = None

@app.route('/api/ftn_latest')
def ftn_latest():
    # Check for trial key to allow API access
    key = request.args.get('key')
    if key:
        valid_keys_json = os.environ.get("VALID_TRIAL_KEYS", "{}")
        try:
            valid_keys = json.loads(valid_keys_json)
        except:
            valid_keys = {}
        
        if key not in valid_keys:
            # If the key is invalid, we still return the score, but we don't add the "pro" flag.
            pass
        else:
            # Key is valid – we can optionally log this access or add a flag.
            logging.info(f"API accessed with trial key: {key}")

    result = compute_daily_ftn()
    if result[0] is None:
        return jsonify({"error": "No data available"}), 500
    score, confidence, sources, raw_score = result

    # Calculate change from yesterday's smoothed score
    daily_avgs = get_daily_average_scores(days=7)
    if len(daily_avgs) >= 7:
        # Yesterday's smoothed = average of the first 6 of the last 7 daily averages
        prev_smoothed = round(sum(daily_avgs[:-1]) / len(daily_avgs[:-1]), 1)
        change = round(score - prev_smoothed, 1)
    else:
        change = 0

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

# ---------- RE‑SEND LAST ALERT ----------
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

# ---------- X AUTO‑POST ----------
@app.route('/post_tweet')
def auto_post():
    try:
        result = compute_daily_ftn()
        if result[0] is None:
            return jsonify({"status": "No score available"})
        score, confidence, sources, raw_score = result

        daily_avgs = get_daily_average_scores(days=7)
        if len(daily_avgs) >= 7:
            prev_smoothed = round(sum(daily_avgs[:-1]) / len(daily_avgs[:-1]), 1)
            change = round(score - prev_smoothed, 1)
        else:
            change = 0

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
