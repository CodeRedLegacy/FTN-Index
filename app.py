import requests
from bs4 import BeautifulSoup
import openai
import os
from flask import Flask, jsonify
import datetime
from collections import deque
import re

app = Flask(__name__)
openai.api_key = os.environ.get("OPENAI_API_KEY")
score_history = deque(maxlen=7)

def scrape_fed_speeches():
url = "https://www.federalreserve.gov/newsevents/speeches.htm"
response = requests.get(url)
soup = BeautifulSoup(response.text, 'html.parser')
speeches = []
for item in soup.select('.item'):
link = item.select_one('a')
if link and 'speech' in link.get('href', ''):
full_url = "https://www.federalreserve.gov" + link['href']
speeches.append(full_url)
return speeches[:3]

def extract_text_from_speech(url):
res = requests.get(url)
soup = BeautifulSoup(res.text, 'html.parser')
article = soup.find('article')
if not article:
return ""
return article.get_text()[:4000]

def score_text_with_ai(text):
prompt = f"""
You are a Federal Reserve communication analyzer. Rate the following text on a scale from 0 (extremely dovish, suggesting rate cuts/easing) to 100 (extremely hawkish, suggesting rate hikes/tightening). Return ONLY the number, no explanation.

Text:
{text}
"""
response = openai.ChatCompletion.create(
model="gpt-4o-mini",
messages=[{"role": "user", "content": prompt}],
temperature=0,
max_tokens=5
)
score_str = response.choices[0].message.content.strip()
digits = re.findall(r'\d+', score_str)
if digits:
score = int(digits[0])
return max(0, min(100, score))
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
app.run(host='0.0.0.0', port=8080)
