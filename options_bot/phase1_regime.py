import os
import json
import smtplib
import requests
import yfinance as yf
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ─── CONFIG ───────────────────────────────────────────────────────────────────
SANDBOX_URL = "https://api.cert.tastyworks.com"
TT_USERNAME  = os.environ["TT_SANDBOX_USERNAME"]
TT_PASSWORD  = os.environ["TT_SANDBOX_PASSWORD"]
TT_ACCOUNT   = os.environ["TT_SANDBOX_ACCOUNT"]
EMAIL_TO     = os.environ["EMAIL_TO"]
EMAIL_FROM   = os.environ["EMAIL_FROM"]
EMAIL_PASS   = os.environ["EMAIL_PASSWORD"]

# ─── TASTYTRADE SESSION ───────────────────────────────────────────────────────
def get_session_token():
    r = requests.post(
        f"{SANDBOX_URL}/sessions",
        json={"login": TT_USERNAME, "password": TT_PASSWORD},
        headers={"Content-Type": "application/json"}
    )
    r.raise_for_status()
    return r.json()["data"]["session-token"]

# ─── MARKET DATA ──────────────────────────────────────────────────────────────
def get_market_data():
    spy  = yf.Ticker("SPY")
    qqq  = yf.Ticker("QQQ")
    vix  = yf.Ticker("^VIX")

    spy_hist = spy.history(period="60d")
    qqq_hist = qqq.history(period="5d")
    vix_hist = vix.history(period="5d")

    spy_close   = spy_hist["Close"]
    spy_price   = round(float(spy_close.iloc[-1]), 2)
    spy_ma20    = round(float(spy_close.rolling(20).mean().iloc[-1]), 2)
    spy_ma50    = round(float(spy_close.rolling(50).mean().iloc[-1]), 2)

    qqq_price   = round(float(qqq_hist["Close"].iloc[-1]), 2)
    qqq_prev    = round(float(qqq_hist["Close"].iloc[-2]), 2)
    spy_prev    = round(float(spy_close.iloc[-2]), 2)

    spy_chg_pct = round(((spy_price - spy_prev) / spy_prev) * 100, 2)
    qqq_chg_pct = round(((qqq_price - qqq_prev) / qqq_prev) * 100, 2)

    vix_price   = round(float(vix_hist["Close"].iloc[-1]), 2)
    vix_prev    = round(float(vix_hist["Close"].iloc[-2]), 2)
    vix_chg     = round(vix_price - vix_prev, 2)
    vix_dir     = "RISING" if vix_chg > 0 else "FALLING"

    return {
        "spy_price":    spy_price,
        "spy_ma20":     spy_ma20,
        "spy_ma50":     spy_ma50,
        "spy_chg_pct":  spy_chg_pct,
        "qqq_chg_pct":  qqq_chg_pct,
        "vix_price":    vix_price,
        "vix_chg":      vix_chg,
        "vix_dir":      vix_dir,
        "spy_above_20": spy_price > spy_ma20,
        "spy_above_50": spy_price > spy_ma50,
        "qqq_leading":  qqq_chg_pct > spy_chg_pct,
    }

# ─── IVR CALCULATOR ───────────────────────────────────────────────────────────
def get_ivr(ticker):
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period="1y")
        if hist.empty:
            return None, None

        # Use High-Low range as a volatility proxy for IVR estimate
        hist["range"] = hist["High"] - hist["Low"]
        current_range = float(hist["range"].iloc[-1])
        high_52w      = float(hist["range"].max())
        low_52w       = float(hist["range"].min())

        if high_52w == low_52w:
            return 50, "NEUTRAL"

        ivr = round(((current_range - low_52w) / (high_52w - low_52w)) * 100, 1)

        if ivr < 25:
            bias = "BUY PREMIUM (debit spreads)"
        elif ivr < 50:
            bias = "BUY-LEAN (debit spreads preferred)"
        elif ivr < 75:
            bias = "NEUTRAL (regime guides)"
        elif ivr < 90:
            bias = "SELL PREMIUM (credit spreads, condors)"
        else:
            bias = "EXTREME — sell far OTM or skip"

        return ivr, bias
    except Exception as e:
        return None, f"Error: {e}"

# ─── EVENT CALENDAR ───────────────────────────────────────────────────────────
def check_event_risk():
    # Known Fed meeting dates 2026 — update quarterly
    fed_dates = [
        date(2026, 1, 29), date(2026, 3, 19),
        date(2026, 4, 29), date(2026, 6, 11),
        date(2026, 7, 29), date(2026, 9, 17),
        date(2026, 11, 5), date(2026, 12, 10),
    ]
    today      = date.today()
    days_ahead = [(d - today).days for d in fed_dates if (d - today).days >= 0]
    nearest    = min(days_ahead) if days_ahead else 99

    if nearest == 0:
        return "FED TODAY", "RED — no new entries"
    elif nearest == 1:
        return f"FED TOMORROW", "RED — reduce exposure"
    elif nearest <= 3:
        return f"FED IN {nearest} DAYS", "YELLOW — smaller size only"
    else:
        return f"Next Fed in {nearest} days", "GREEN — no event risk"

# ─── REGIME CLASSIFIER ────────────────────────────────────────────────────────
def classify_regime(data, vix):
    above_20 = data["spy_above_20"]
    above_50 = data["spy_above_50"]
    qqq_lead = data["qqq_leading"]
    vix_val  = data["vix_price"]
    vix_dir  = data["vix_dir"]
    spy_chg  = abs(data["spy_chg_pct"])

    # Regime D — High Volatility (check first)
    if vix_val > 28 or (vix_val > 22 and spy_chg > 2.0):
        return "D", "HIGH VOLATILITY / RISK-OFF", [
            "Smaller defined-risk spreads only",
            "Far OTM positions only",
            "Reduce exposure — more cash",
            "No aggressive directional bets",
        ]

    # Regime A — Bull Trend
    if above_20 and above_50 and vix_dir == "FALLING" and vix_val < 20:
        return "A", "BULL TREND", [
            "Bull call debit spread",
            "Put credit spread",
            "Cash-secured put (on names you want to own)",
            "Covered call on owned shares",
        ]

    # Regime B — Bear Trend
    if not above_20 and not above_50 and vix_dir == "RISING":
        return "B", "BEAR TREND / DOWNTREND", [
            "Bear put debit spread",
            "Call credit spread",
            "Protective put as hedge",
            "Reduce bullish exposure",
        ]

    # Regime C — Range / Chop
    if (above_50 and not above_20) or (above_20 and vix_val >= 18):
        return "C", "RANGE / CHOP", [
            "Iron condor",
            "Put credit spread",
            "Call credit spread",
            "Calendar spread",
        ]

    # Default fallback
    return "C", "RANGE / CHOP (default)", [
        "Iron condor",
        "Credit spreads",
        "Covered call",
    ]

# ─── GRADE SYSTEM ─────────────────────────────────────────────────────────────
def calculate_grade(regime_id, ivr, vix, event_color, spy_chg):
    score = 0

    # Regime clarity (20 pts)
    if regime_id in ["A", "B", "C"]:
        score += 20
    elif regime_id == "E":
        score += 5
    else:
        score += 8  # D

    # IVR alignment (20 pts)
    if ivr is not None:
        if (regime_id in ["A","B"] and ivr < 50) or \
           (regime_id == "C" and 40 < ivr < 85):
            score += 20
        elif 25 <= ivr <= 75:
            score += 12
        else:
            score += 6

    # VIX cooperative (20 pts)
    if vix < 18:
        score += 20
    elif vix < 22:
        score += 14
    elif vix < 28:
        score += 8
    else:
        score += 2

    # Event risk clear (20 pts)
    if event_color == "GREEN":
        score += 20
    elif event_color == "YELLOW":
        score += 10
    else:
        score += 0

    # SPY daily stability (20 pts)
    if abs(spy_chg) < 0.8:
        score += 20
    elif abs(spy_chg) < 1.5:
        score += 12
    elif abs(spy_chg) < 2.0:
        score += 6
    else:
        score += 0

    # Convert to grade
    if score >= 90:
        return score, "A+", "STRONG RECOMMEND — full size"
    elif score >= 80:
        return score, "A",  "RECOMMEND — full size"
    elif score >= 70:
        return score, "A-", "RECOMMEND — slightly reduced size"
    elif score >= 60:
        return score, "B+", "BORDERLINE — present to you"
    elif score >= 50:
        return score, "B",  "GRAY ZONE — your call"
    elif score >= 40:
        return score, "B-", "GRAY ZONE — lean toward skip"
    else:
        return score, "—",  "INSUFFICIENT EDGE — not presented"

# ─── EMAIL BUILDER ────────────────────────────────────────────────────────────
def build_email(data, regime, regime_label, strategies,
                ivr, ivr_bias, event_label, event_color,
                score, grade, grade_desc):

    today_str  = datetime.now().strftime("%A, %B %d %Y — %I:%M %p PT")
    spy_vs_20  = "ABOVE" if data["spy_above_20"] else "BELOW"
    spy_vs_50  = "ABOVE" if data["spy_above_50"] else "BELOW"
    qqq_status = "LEADING SPY" if data["qqq_leading"] else "LAGGING SPY"

    grade_emoji = {
        "A+": "🟢", "A": "🟢", "A-": "🟢",
        "B+": "🟡", "B": "🟡", "B-": "🔴", "—": "🔴"
    }.get(grade, "⚪")

    strat_lines = "\n".join([f"  • {s}" for s in strategies])

    body = f"""
╔══════════════════════════════════════════╗
   OPTIONS BOT — DAILY REGIME REPORT
   {today_str}
╚══════════════════════════════════════════╝

━━━ REGIME ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  REGIME {regime} — {regime_label}

━━━ MARKET DATA ━━━━━━━━━━━━━━━━━━━━━━━━━
  SPY:    ${data['spy_price']}  ({data['spy_chg_pct']:+.2f}%)
  MA20:   ${data['spy_ma20']}  → SPY is {spy_vs_20} 20-day MA
  MA50:   ${data['spy_ma50']}  → SPY is {spy_vs_50} 50-day MA
  QQQ:    {data['qqq_chg_pct']:+.2f}%  → {qqq_status}
  VIX:    {data['vix_price']}  ({data['vix_chg']:+.2f})  → {data['vix_dir']}

━━━ IVR (SPY) ━━━━━━━━━━━━━━━━━━━━━━━━━━━
  IVR:    {ivr if ivr else 'N/A'}
  Bias:   {ivr_bias}

━━━ EVENT RISK ━━━━━━━━━━━━━━━━━━━━━━━━━━
  {event_label}
  Status: {event_color}

━━━ TODAY'S GRADE ━━━━━━━━━━━━━━━━━━━━━━━
  {grade_emoji} GRADE: {grade}  ({score}/100)
  {grade_desc}

━━━ STRATEGY CANDIDATES ━━━━━━━━━━━━━━━━━
{strat_lines}

━━━ FRAMEWORK REMINDER ━━━━━━━━━━━━━━━━━━
  1. Regime first — always
  2. IVR guides buy vs sell bias
  3. Greeks filter before any entry
  4. No trade is a valid decision
  5. Execute only what YOU confirm

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Options Bot v1.0 | Phase 1 — Regime Engine
  Next: Greeks + options chain scan (Phase 3)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    return body

# ─── SEND EMAIL ───────────────────────────────────────────────────────────────
def send_email(subject, body):
    msg            = MIMEMultipart()
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASS)
        server.send_message(msg)
    print("Email sent.")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print("Fetching market data...")
    data = get_market_data()

    print("Calculating IVR...")
    ivr, ivr_bias = get_ivr("SPY")

    print("Checking event risk...")
    event_label, event_status = check_event_risk()
    event_color = event_status.split("—")[0].strip()

    print("Classifying regime...")
    regime, regime_label, strategies = classify_regime(data, data["vix_price"])

    print("Calculating grade...")
    score, grade, grade_desc = calculate_grade(
        regime, ivr, data["vix_price"], event_color, data["spy_chg_pct"]
    )

    print(f"Regime: {regime} — {regime_label}")
    print(f"Grade:  {grade} ({score}/100)")

    body    = build_email(data, regime, regime_label, strategies,
                          ivr, ivr_bias, event_label, event_status,
                          score, grade, grade_desc)
    subject = f"OPTIONS BOT | Regime {regime} | Grade {grade} | VIX {data['vix_price']} | {datetime.now().strftime('%b %d')}"

    send_email(subject, body)

if __name__ == "__main__":
    main()
