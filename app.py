<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>F‑Tone (FTN) – AI‑Powered Fed Sentiment Index</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0e14;
            color: #e6e1cf;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            line-height: 1.6;
            padding: 40px 20px;
            max-width: 720px;
            margin: 0 auto;
        }
        h1 {
            color: #ffb454;
            font-size: 28px;
            margin-bottom: 8px;
        }
        .subtitle {
            color: #8b95a5;
            font-size: 16px;
            margin-bottom: 30px;
        }
        h2 {
            color: #f2c94c;
            font-size: 20px;
            margin: 40px 0 12px;
        }
        p, li {
            color: #b0bdcf;
            font-size: 15px;
            margin-bottom: 12px;
        }
        .card {
            background: #131820;
            border: 1px solid #2a3342;
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 20px;
        }
        .features {
            list-style: none;
            padding: 0;
            margin: 0;
        }
        .features li {
            margin-bottom: 10px;
            padding-left: 20px;
            position: relative;
        }
        .features li::before {
            content: "▹";
            color: #ffb454;
            position: absolute;
            left: 0;
        }
        .cta {
            margin: 40px 0;
            text-align: center;
        }
        .cta a {
            display: inline-block;
            background: #ffb454;
            color: #0a0e14;
            font-weight: 700;
            font-size: 16px;
            padding: 12px 28px;
            border-radius: 8px;
            text-decoration: none;
        }
        .cta a:hover {
            background: #ffc870;
        }
        .footer {
            border-top: 1px solid #1e2733;
            padding-top: 20px;
            margin-top: 40px;
            font-size: 13px;
            color: #5a6577;
        }
        .footer a {
            color: #58a6ff;
            text-decoration: none;
            margin-right: 15px;
        }
        .footer a:hover { text-decoration: underline; }
        .logo {
            font-size: 22px;
            font-weight: 700;
            color: #ffb454;
            letter-spacing: 0.04em;
        }
        @media (max-width: 480px) {
            body { padding: 20px 16px; }
            h1 { font-size: 24px; }
        }
    </style>
</head>
<body>

    <div class="logo">F‑Tone (FTN)</div>
    <h1>AI‑Powered Federal Reserve Sentiment Index</h1>
    <p class="subtitle">Daily hawkish‑dovish gauge on a 0–100 scale. Transparent. Real‑time. Free.</p>

    <div class="card">
        <h2>What is FTN?</h2>
        <p>
            The F‑Tone Index measures the tone of Federal Reserve communications—
            speeches, FOMC statements, and minutes—using artificial intelligence.
            On every visit, our system reads the latest available primary sources,
            assigns a hawkish/dovish score to each, and publishes a fresh 0–100 reading.
        </p>
        <p>
            The dashboard displays <strong>two values, in the format 73.6 → 71.2</strong>:
            the <strong>raw instant score</strong> (the simple average of all individual document scores from the current analysis)
            and the <strong>smoothed 7‑day moving average</strong>, so you can see both the immediate
            reaction and the underlying trend.
        </p>
        <p>
            <strong>0 = extremely dovish</strong> (signalling rate cuts / easing) &nbsp;|&nbsp;
            <strong>100 = extremely hawkish</strong> (signalling rate hikes / tightening)
        </p>
    </div>

    <h2>Why FTN?</h2>
    <ul class="features">
        <li><strong>Transparent methodology</strong> – every reading is linked to the source documents that produced it, with speaker attribution.</li>
        <li><strong>Confidence‑weighted</strong> – HIGH / MEDIUM / LOW based on the breadth of sources analysed.</li>
        <li><strong>No black boxes</strong> – the index is free and the raw API is publicly accessible.</li>
        <li><strong>Always fresh</strong> – recalculated with every request, while a background process keeps the data pipeline warm 24/7, so you always see a <strong>real‑time assessment</strong>.</li>
        <li><strong>Built for professionals</strong> – designed for journalists, analysts, and fund managers who need a quick, objective Fed sentiment read.</li>
    </ul>

    <h2>Methodology at a Glance</h2>
    <div class="card">
        <p>
            <strong>1. Data collection</strong> – we scrape the latest Federal Reserve speeches, FOMC statements, and minutes.
        </p>
        <p>
            <strong>2. AI scoring</strong> – each document is passed to a large language model instructed to rate the tone from 0 (dovish) to 100 (hawkish). The model considers the text's language regarding inflation, employment, economic growth, and policy guidance.
        </p>
        <p>
            <strong>3. Smoothing</strong> – the raw scores are averaged (simple mean across the day's documents) and then run through a 7‑day moving window to produce the smoothed FTN value. Both the raw (instant) and smoothed values are shown on the dashboard.
        </p>
        <p>
            <strong>4. Qualitative label</strong> – the “Hawkish” / “Dovish” label normally follows the smoothed score. However, if the raw score makes a sharp move (≥ 5 points) in the opposite direction, the label switches to reflect the raw score instead — acting as an early warning of a potential trend change.
        </p>
        <p>
            <strong>5. Confidence estimation</strong> – the number of sources and total text volume determine the confidence label.
        </p>
    </div>

    <h2>Get Access</h2>
    <div class="card">
        <p>
            The live dashboard is available to everyone, no login required.<br>
            A <strong>free JSON API</strong> is also available for non‑commercial use.
        </p>
        <p>
            For API access, trial subscriptions, or press inquiries, contact us directly:
        </p>
        <p style="text-align: center; margin: 20px 0;">
            <a href="mailto:ftone.index@gmail.com" style="color:#58a6ff; font-weight:600; text-decoration:none;">ftone.index@gmail.com</a>
            &nbsp;|&nbsp;
            <a href="https://x.com/FToneIndex" target="_blank" style="color:#58a6ff; font-weight:600; text-decoration:none;">@FToneIndex</a>
        </p>
    </div>

    <h2>Pricing</h2>
    <div class="card" style="text-align:center;">
        <div style="display:flex; flex-wrap:wrap; justify-content:center; gap:20px; margin:20px 0;">
            
            <div style="flex:1; min-width:200px; border:1px solid #2a3342; border-radius:12px; padding:20px;">
                <h3 style="color:#8b95a5; margin:0 0 10px;">Free</h3>
                <div style="font-size:32px; font-weight:700; color:#e6e1cf; margin:10px 0;">$0</div>
                <p style="font-size:14px; color:#8b95a5; margin:10px 0;">Delayed dashboard<br>24‑hour data lag<br>No API access</p>
            </div>
            
            <div style="flex:1; min-width:200px; border:2px solid #ffb454; border-radius:12px; padding:20px; background:#1a1f2e;">
                <div style="display:inline-block; background:#ffb454; color:#0a0e14; font-size:12px; font-weight:700; padding:3px 10px; border-radius:10px; margin-bottom:8px;">LAUNCH SPECIAL</div>
                <h3 style="color:#ffb454; margin:0 0 10px;">Pro</h3>
                <div style="font-size:32px; font-weight:700; color:#e6e1cf; margin:10px 0;">$99 🔒<span style="font-size:16px; color:#8b95a5;">/month</span></div>
                <div style="font-size:16px; font-weight:600; color:#f2c94c; margin:5px 0; background:#2a2a1a; padding:4px 10px; border-radius:8px; display:inline-block;">Standard: $199/month</div>
                <p style="font-size:14px; color:#b0bdcf; margin:10px 0;">Real‑time API<br>Live dashboard<br>Backtestable CSV</p>
                <div style="background:#1a3a2a; color:#4fc97a; font-size:13px; font-weight:600; padding:5px 12px; border-radius:10px; margin-top:10px; display:inline-block;">🔒 First 20 subscribers — lifetime lock</div>
            </div>
            
            <div style="flex:1; min-width:200px; border:1px solid #2a3342; border-radius:12px; padding:20px;">
                <h3 style="color:#f2c94c; margin:0 0 10px;">Enterprise</h3>
                <div style="font-size:32px; font-weight:700; color:#e6e1cf; margin:10px 0;">$999<span style="font-size:16px; color:#8b95a5;">/month</span></div>
                <p style="font-size:14px; color:#b0bdcf; margin:10px 0;">Custom integration<br>Dedicated support<br>Co‑branding rights<br>Quarterly briefings</p>
            </div>
            
        </div>
        <p style="font-size:13px; color:#5a6577;">All plans include access to the live dashboard. Pro and Enterprise include API access. <a href="mailto:ftone.index@gmail.com" style="color:#58a6ff;">Contact us</a> for trials and inquiries.</p>
    </div>

    <div class="cta">
        <a href="https://ftone-index.github.io/ftone-dashboard/" target="_blank">View the Live Dashboard →</a>
    </div>

    <div class="footer">
        <a href="https://ftone-index.github.io/ftone-dashboard/">Dashboard</a>
        <a href="https://ftone-index.github.io/ftone-dashboard/legal/terms.html">Terms of Service</a>
        <a href="https://x.com/FToneIndex">X / Twitter</a>
        <br><br>
        © 2026 F‑Tone Index. All rights reserved.
    </div>

</body>
</html>
