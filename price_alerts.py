import yfinance as yf
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import pytz

# ============================================================
# YOUR ALERT LEVELS — UPDATE WHEN LEVELS CHANGE
# ============================================================
ALERTS = [
    # ticker, name, buy_s1, buy_s2, breakout_r1, danger_level, avg_cost
    {"ticker": "SPY",  "name": "S&P 500 ETF",         "s1": 645,   "s2": 635,   "r1": 668,   "danger": 635,   "avg": 673.15},
    {"ticker": "QQQ",  "name": "Invesco QQQ",          "s1": 580,   "s2": 570,   "r1": 598,   "danger": 570,   "avg": 597.57},
    {"ticker": "SOXX", "name": "Semiconductor ETF",    "s1": 332,   "s2": 320,   "r1": 358,   "danger": 320,   "avg": 330.78},
    {"ticker": "AAPL", "name": "Apple",                "s1": 248,   "s2": 240,   "r1": 262,   "danger": 240,   "avg": 257.30},
    {"ticker": "NVDA", "name": "Nvidia",               "s1": 172,   "s2": 162,   "r1": 190,   "danger": 162,   "avg": 181.46},
    {"ticker": "MU",   "name": "Micron Technology",    "s1": 370,   "s2": 358,   "r1": 395,   "danger": 358,   "avg": 376.93},
    {"ticker": "XLI",  "name": "Industrials SPDR",     "s1": 160,   "s2": 154,   "r1": 170,   "danger": 154,   "avg": 169.10},
    {"ticker": "XLV",  "name": "Healthcare SPDR",      "s1": 143,   "s2": 138,   "r1": 150,   "danger": 138,   "avg": 156.27},
    {"ticker": "IAU",  "name": "iShares Gold Trust",   "s1": 82,    "s2": 78,    "r1": 88,    "danger": 78,    "avg": 93.76},
    {"ticker": "KBWB", "name": "KBW Bank ETF",         "s1": 76,    "s2": 72,    "r1": 82,    "danger": 72,    "avg": 80.14},
    {"ticker": "BTC-USD", "name": "Bitcoin",           "s1": 65000, "s2": 60000, "r1": 76000, "danger": 60000, "avg": 71896.01},
]

RECIPIENT_EMAIL = "julioir89@gmail.com"
TIMEZONE = "America/Los_Angeles"

# ============================================================
# FETCH LIVE PRICES FROM YAHOO FINANCE
# ============================================================
def fetch_prices():
    tickers = [a["ticker"] for a in ALERTS]
    data = yf.download(tickers, period="1d", interval="5m", progress=False)
    prices = {}
    for ticker in tickers:
        try:
            if len(tickers) > 1:
                price = float(data["Close"][ticker].dropna().iloc[-1])
            else:
                price = float(data["Close"].dropna().iloc[-1])
            prices[ticker] = round(price, 2)
        except Exception as e:
            print(f"Could not fetch {ticker}: {e}")
            prices[ticker] = None
    return prices

# ============================================================
# CHECK ALERT CONDITIONS
# ============================================================
def check_alerts(prices):
    triggered = []

    for asset in ALERTS:
        ticker = asset["ticker"]
        price = prices.get(ticker)
        if price is None:
            continue

        name = asset["name"]
        display = "BTC" if ticker == "BTC-USD" else ticker

        # ── BUY ALERTS (at or below S1) ──────────────────
        if price <= asset["s1"] and price > asset["s2"]:
            pct_from_avg = ((price - asset["avg"]) / asset["avg"]) * 100
            triggered.append({
                "type": "BUY",
                "color": "🟢",
                "ticker": display,
                "name": name,
                "price": price,
                "message": f"At S1 buy zone (${asset['s1']})",
                "action": f"DCA entry. Avg cost ${asset['avg']}. Currently {pct_from_avg:.1f}% from avg.",
                "urgency": "MEDIUM",
            })

        # ── DEEP BUY ALERTS (at or below S2) ─────────────
        if price <= asset["s2"]:
            pct_from_avg = ((price - asset["avg"]) / asset["avg"]) * 100
            triggered.append({
                "type": "DEEP BUY",
                "color": "💰",
                "ticker": display,
                "name": name,
                "price": price,
                "message": f"At S2 deep buy zone (${asset['s2']})",
                "action": f"Strong DCA opportunity. Avg cost ${asset['avg']}. Currently {pct_from_avg:.1f}% from avg.",
                "urgency": "HIGH",
            })

        # ── BREAKOUT ALERTS (cleared R1) ──────────────────
        if price >= asset["r1"]:
            pct_gain = ((price - asset["avg"]) / asset["avg"]) * 100
            triggered.append({
                "type": "BREAKOUT",
                "color": "🔵",
                "ticker": display,
                "name": name,
                "price": price,
                "message": f"Cleared R1 resistance (${asset['r1']})",
                "action": f"Confirm strength before adding. Now {pct_gain:.1f}% above avg cost.",
                "urgency": "MEDIUM",
            })

        # ── DANGER ALERTS (broke below S2) ───────────────
        if price < asset["danger"]:
            triggered.append({
                "type": "DANGER",
                "color": "🔴",
                "ticker": display,
                "name": name,
                "price": price,
                "message": f"BROKE below danger level (${asset['danger']})",
                "action": "DO NOT ADD. Reassess position. Capital preservation mode.",
                "urgency": "CRITICAL",
            })

    return triggered

# ============================================================
# BUILD EMAIL
# ============================================================
def build_email(triggered, prices, all_assets):
    la_tz = pytz.timezone(TIMEZONE)
    now = datetime.now(la_tz)
    time_str = now.strftime("%I:%M %p PT · %A, %B %d")

    if not triggered:
        return None, None  # No alerts = no email

    # Sort by urgency
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
    triggered.sort(key=lambda x: order.get(x["urgency"], 3))

    subject_types = list(set([t["type"] for t in triggered]))
    subject = f"⚡ PORTFOLIO ALERT — {' · '.join(subject_types)} ({len(triggered)} trigger{'s' if len(triggered) > 1 else ''})"

    # Build plain text
    lines = [
        f"PORTFOLIO ALERT SYSTEM",
        f"{time_str}",
        f"{'='*50}",
        f"{len(triggered)} ALERT(S) TRIGGERED",
        f"{'='*50}",
        "",
    ]

    for alert in triggered:
        lines += [
            f"{alert['color']} {alert['type']} — {alert['ticker']} ({alert['name']})",
            f"   Price: ${alert['price']:,.2f}",
            f"   Signal: {alert['message']}",
            f"   Action: {alert['action']}",
            f"   Urgency: {alert['urgency']}",
            "",
        ]

    lines += [
        "─"*50,
        "CURRENT PORTFOLIO PRICES",
        "─"*50,
    ]
    for asset in all_assets:
        ticker = asset["ticker"]
        display = "BTC" if ticker == "BTC-USD" else ticker
        price = prices.get(ticker)
        if price:
            pct = ((price - asset["avg"]) / asset["avg"]) * 100
            direction = "▲" if pct >= 0 else "▼"
            lines.append(f"  {display:<6} ${price:>10,.2f}   {direction} {abs(pct):.1f}% vs avg")

    lines += ["", "─"*50, "Automated Alert · Julio's Portfolio System · Claude AI"]
    plain_text = "\n".join(lines)

    # Build HTML
    alert_rows = ""
    type_colors = {"BUY": "#22c55e", "DEEP BUY": "#16a34a", "BREAKOUT": "#3b82f6", "DANGER": "#ef4444"}

    for alert in triggered:
        color = type_colors.get(alert["type"], "#c9a84c")
        alert_rows += f"""
        <div style="border-left: 4px solid {color}; background: #0f1520;
                    padding: 14px 16px; margin-bottom: 10px; border-radius: 0 6px 6px 0;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span style="font-size:14px; font-weight:bold; color:{color};">
              {alert['color']} {alert['type']} — {alert['ticker']}
            </span>
            <span style="font-size:10px; color:#555; background:#1a1f2e;
                         padding:3px 8px; border-radius:3px;">{alert['urgency']}</span>
          </div>
          <div style="font-size:11px; color:#888; margin-bottom:4px;">{alert['name']}</div>
          <div style="font-size:18px; font-weight:bold; color:#fff; margin-bottom:6px;">
            ${alert['price']:,.2f}
          </div>
          <div style="font-size:11px; color:#aaa; margin-bottom:4px;">📍 {alert['message']}</div>
          <div style="font-size:11px; color:{color};">→ {alert['action']}</div>
        </div>"""

    price_rows = ""
    for asset in all_assets:
        ticker = asset["ticker"]
        display = "BTC" if ticker == "BTC-USD" else ticker
        price = prices.get(ticker)
        if price:
            pct = ((price - asset["avg"]) / asset["avg"]) * 100
            pct_color = "#22c55e" if pct >= 0 else "#ef4444"
            direction = "▲" if pct >= 0 else "▼"
            price_rows += f"""
            <tr>
              <td style="padding:6px 10px; color:#fff; font-weight:bold;">{display}</td>
              <td style="padding:6px 10px; color:#ccc;">${price:,.2f}</td>
              <td style="padding:6px 10px; color:{pct_color};">{direction} {abs(pct):.1f}%</td>
              <td style="padding:6px 10px; color:#555;">${asset['avg']:,.2f}</td>
            </tr>"""

    html = f"""
<html>
<body style="font-family:'Courier New',monospace; background:#080b10;
             color:#e0e0e0; padding:20px; max-width:640px; margin:0 auto;">

  <div style="border:1px solid #c9a84c; border-radius:8px; padding:16px; margin-bottom:16px;">
    <div style="color:#c9a84c; font-size:10px; letter-spacing:3px; margin-bottom:4px;">
      PORTFOLIO ALERT SYSTEM
    </div>
    <div style="font-size:18px; font-weight:bold; color:#fff; margin-bottom:2px;">
      ⚡ {len(triggered)} ALERT{'S' if len(triggered) > 1 else ''} TRIGGERED
    </div>
    <div style="font-size:11px; color:#555;">{time_str}</div>
  </div>

  <div style="margin-bottom:16px;">
    {alert_rows}
  </div>

  <div style="border:1px solid #1a1f2e; border-radius:8px; overflow:hidden; margin-bottom:16px;">
    <div style="background:#0d1117; padding:10px 14px; font-size:10px;
                color:#888; letter-spacing:2px; border-bottom:1px solid #1a1f2e;">
      CURRENT PORTFOLIO PRICES
    </div>
    <table style="width:100%; border-collapse:collapse; background:#080b10;">
      <tr style="background:#0a0d14;">
        <td style="padding:6px 10px; color:#555; font-size:9px;">TICKER</td>
        <td style="padding:6px 10px; color:#555; font-size:9px;">PRICE</td>
        <td style="padding:6px 10px; color:#555; font-size:9px;">VS AVG</td>
        <td style="padding:6px 10px; color:#555; font-size:9px;">AVG COST</td>
      </tr>
      {price_rows}
    </table>
  </div>

  <div style="text-align:center; font-size:10px; color:#333; padding:8px;">
    Automated Alert · Julio's Portfolio System · Powered by Claude AI
  </div>
</body>
</html>"""

    return subject, plain_text, html

# ============================================================
# SEND EMAIL
# ============================================================
def send_alert_email(subject, plain_text, html):
    sender = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Portfolio Alerts <{sender}>"
    msg["To"] = RECIPIENT_EMAIL

    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, RECIPIENT_EMAIL, msg.as_string())

    print(f"✅ Alert email sent — {len(triggered)} trigger(s)")

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("📡 Fetching live prices from Yahoo Finance...")
    prices = fetch_prices()

    for asset in ALERTS:
        display = "BTC" if asset["ticker"] == "BTC-USD" else asset["ticker"]
        print(f"  {display}: ${prices.get(asset['ticker'], 'N/A')}")

    print("\n🔍 Checking alert conditions...")
    triggered = check_alerts(prices)

    if not triggered:
        print("✅ No alerts triggered. All levels holding.")
    else:
        print(f"⚡ {len(triggered)} alert(s) triggered!")
        result = build_email(triggered, prices, ALERTS)
        if result[0]:
            subject, plain_text, html = result
            send_alert_email(subject, plain_text, html)
