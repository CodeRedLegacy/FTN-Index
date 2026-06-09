# ---------- MARKET EXPECTATION ENDPOINT (Solution B, robust) ----------
def compute_market_ftn():
    """
    Returns a 0‑100 score representing what the market is pricing in
    about the Fed's next moves, derived from:
      - CME FedWatch (probability of next rate hike)
      - 2y/10y Treasury spread (via FRED)
      - US Dollar Index (DXY) (via Yahoo Finance)
    Falls back gracefully if any source is unavailable.
    """
    hike_prob = 50        # neutral default
    spread = 0            # neutral default
    dxy_change = 0        # neutral default

    # 1. CME FedWatch – with longer timeout and error handling
    try:
        fedwatch_url = "https://www.cmegroup.com/CmeWS/mvc/InterestRates/FOMC/Current"
        fw_response = requests.get(fedwatch_url, timeout=25)
        if fw_response.status_code == 200:
            fw_json = fw_response.json()
            meetings = fw_json.get("meetings", [])
            if meetings:
                for outcome in meetings[0].get("outcomes", []):
                    if "higher" in outcome.get("label", "").lower() or "hike" in outcome.get("label", "").lower():
                        hike_prob = outcome.get("probability", 50)
                        break
        else:
            logging.warning(f"CME FedWatch returned status {fw_response.status_code}")
    except requests.exceptions.Timeout:
        logging.warning("CME FedWatch timed out – using default hike_prob=50")
    except Exception as e:
        logging.warning(f"CME FedWatch error: {e}")

    # 2. FRED spread – only if we have a FRED API key
    fred_api_key = os.environ.get("FRED_API_KEY")
    if fred_api_key:
        try:
            fred_2y = requests.get(
                f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS2&api_key={fred_api_key}&file_type=json&sort_order=desc&limit=1",
                timeout=15
            )
            fred_10y = requests.get(
                f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key={fred_api_key}&file_type=json&sort_order=desc&limit=1",
                timeout=15
            )
            if fred_2y.status_code == 200 and fred_10y.status_code == 200:
                obs_2y = fred_2y.json().get("observations", [])
                obs_10y = fred_10y.json().get("observations", [])
                if obs_2y and obs_10y:
                    y2 = float(obs_2y[0].get("value", 0) or 0)
                    y10 = float(obs_10y[0].get("value", 0) or 0)
                    if y2 and y10:
                        spread = y10 - y2
        except Exception as e:
            logging.warning(f"FRED error: {e}")

    # 3. DXY via Yahoo Finance (lightweight, rarely fails)
    try:
        dxy_url = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1d&range=1d"
        dxy_response = requests.get(dxy_url, timeout=15)
        if dxy_response.status_code == 200:
            dxy_json = dxy_response.json()
            result = dxy_json.get("chart", {}).get("result", [])
            if result:
                meta = result[0].get("meta", {})
                prev_close = meta.get("previousClose")
                current = meta.get("regularMarketPrice")
                if prev_close and current:
                    dxy_change = ((current / prev_close) - 1) * 100
    except Exception as e:
        logging.warning(f"DXY error: {e}")

    # Combine into a single 0‑100 score
    # hike_prob is already 0‑100
    spread_score = min(100, max(0, 50 + spread * 50))
    dxy_score = min(100, max(0, 50 + dxy_change * 100))

    market_ftn = round((hike_prob + spread_score + dxy_score) / 3, 1)

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
        "hike_prob": hike_prob,
        "spread": spread,
        "dxy_change": dxy_change
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
