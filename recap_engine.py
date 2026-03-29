import yfinance as yf
import smtplib
import os
import feedparser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import pytz

# ============================================================
# CONFIGURATION
# ============================================================
RECIPIENT_EMAIL = "julioir89@gmail.com"
TIMEZONE = "America/Los_Angeles"

HOLDINGS = [
    {"ticker": "SPY",     "name": "S&P 500 ETF",          "avg": 673.15, "shares": 0.22775, "s1": 645,   "s2": 635,   "r1": 668,   "r2": 680,   "role": "Market Base"},
    {"ticker": "QQQ",     "name": "Invesco QQQ",           "avg": 597.57, "shares": 0.14075, "s1": 580,   "s2": 570,   "r1": 598,   "r2": 610,   "role": "Growth Engine"},
    {"ticker": "SOXX",    "name": "Semiconductor ETF",     "avg": 330.78, "shares": 0.18441, "s1": 332,   "s2": 320,   "r1": 358,   "r2": 370,   "role": "Semi Leverage"},
    {"ticker": "AAPL",    "name": "Apple",                 "avg": 257.30, "shares": 0.35021, "s1": 248,   "s2": 240,   "r1": 262,   "r2": 272,   "role": "Stability"},
    {"ticker": "NVDA",    "name": "Nvidia",                "avg": 181.46, "shares": 0.55107, "s1": 172,   "s2": 162,   "r1": 190,   "r2": 200,   "role": "AI Leader"},
    {"ticker": "MU",      "name": "Micron Technology",     "avg": 376.93, "shares": 0.16183, "s1": 370,   "s2": 358,   "r1": 395,   "r2": 408,   "role": "High Beta Semi"},
    {"ticker": "XLI",     "name": "Industrials SPDR",      "avg": 169.10, "shares": 0.34299, "s1": 160,   "s2": 154,   "r1": 170,   "r2": 176,   "role": "Cyclical"},
    {"ticker": "XLV",     "name": "Healthcare SPDR",       "avg": 156.27, "shares": 0.25475, "s1": 143,   "s2": 138,   "r1": 150,   "r2": 155,   "role": "Defensive"},
    {"ticker": "IAU",     "name": "iShares Gold Trust",    "avg": 93.76,  "shares": 0.30930, "s1": 82,    "s2": 78,    "r1": 88,    "r2": 93,    "role": "Macro Hedge"},
    {"ticker": "KBWB",    "name": "KBW Bank ETF",          "avg": 80.14,  "shares": 0.56149, "s1": 76,    "s2": 72,    "r1": 82,    "r2": 86,    "role": "Banking"},
    {"ticker": "BTC-USD", "name": "Bitcoin",               "avg": 71896,  "shares": 0.00085, "s1": 65000, "s2": 60000, "r1": 76000, "r2": 82000, "role": "Risk Proxy"},
]

MACRO_TICKERS = {
    "^VIX":   "VIX Fear Index",
    "GC=F":   "Gold Futures",
    "CL=F":   "Oil (WTI)",
    "^TNX":   "10Y Treasury Yield",
    "DX-Y.NYB": "US Dollar Index",
}

NEWS_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY,QQQ,NVDA,AAPL,MU&region=US&lang=en-US",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
]

# ============================================================
# FETCH LIVE PRICES
# ============================================================
def fetch_prices():
    tickers = [h["ticker"] for h in HOLDINGS]
    prices = {}
    try:
        data = yf.download(tickers, period="2d", interval="1d", progress=False, auto_adjust=True)
        for ticker in tickers:
            try:
                series = data["Close"][ticker].dropna()
                prices[ticker] = {
                    "current": round(float(series.iloc[-1]), 2),
                    "prev":    round(float(series.iloc[-2]), 2) if len(series) > 1 else None,
                }
            except:
                prices[ticker] = {"current": None, "prev": None}
    except Exception as e:
        print(f"Price fetch error: {e}")
    return prices

def fetch_macro():
    macro = {}
    try:
        tickers = list(MACRO_TICKERS.keys())
        data = yf.download(tickers, period="2d", interval="1d", progress=False, auto_adjust=True)
        for ticker in tickers:
            try:
                series = data["Close"][ticker].dropna()
                current = round(float(series.iloc[-1]), 2)
                prev    = round(float(series.iloc[-2]), 2) if len(series) > 1 else current
                change  = round(((current - prev) / prev) * 100, 2) if prev else 0
                macro[ticker] = {"current": current, "prev": prev, "change": change, "name": MACRO_TICKERS[ticker]}
            except:
                macro[ticker] = {"current": None, "prev": None, "change": 0, "name": MACRO_TICKERS[ticker]}
    except Exception as e:
        print(f"Macro fetch error: {e}")
    return macro

# ============================================================
# FETCH NEWS HEADLINES
# ============================================================
def fetch_news(max_items=8):
    headlines = []
    seen = set()
    for url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:4]:
                title = entry.get("title", "").strip()
                if title and title not in seen and len(title) > 20:
                    seen.add(title)
                    headlines.append({
                        "title":  title,
                        "source": feed.feed.get("title", "News"),
                        "link":   entry.get("link", ""),
                    })
                if len(headlines) >= max_items:
                    break
        except Exception as e:
            print(f"News feed error ({url}): {e}")
        if len(headlines) >= max_items:
            break
    return headlines[:max_items]

# ============================================================
# ANALYSIS LOGIC
# ============================================================
def get_dca_status(price, s1, s2, r1):
    if price is None:
        return "N/A", "#888"
    dist_s1 = ((price - s1) / price) * 100
    if price <= s2:
        return "💰 DEEP BUY", "#22c55e"
    if dist_s1 <= 1.5:
        return "✅ AT S1", "#22c55e"
    if dist_s1 <= 4.0:
        return "⚠️ NEAR S1", "#c9a84c"
    if price >= r1:
        return "🔵 AT R1", "#3b82f6"
    return "❌ WAIT", "#888"

def calc_market_score(prices):
    score = 0
    above_s1 = sum(1 for h in HOLDINGS if prices.get(h["ticker"], {}).get("current") and
                   prices[h["ticker"]]["current"] > h["s1"])
    score += round((above_s1 / len(HOLDINGS)) * 35)

    spy_price = prices.get("SPY", {}).get("current")
    if spy_price:
        spy_pct = ((spy_price - 673.15) / 673.15) * 100
        score += 25 if spy_pct > 0 else 18 if spy_pct > -3 else 10 if spy_pct > -6 else 4

    qqq_above = prices.get("QQQ", {}).get("current", 0) > 580
    soxx_above = prices.get("SOXX", {}).get("current", 0) > 332
    score += 25 if (qqq_above and soxx_above) else 12

    xlv_price = prices.get("XLV", {}).get("current")
    score += 10 if xlv_price and xlv_price < 156.27 else 15

    return min(100, score)

def get_risk_dial(score):
    if score >= 70: return "AGGRESSIVE", "▲▲▲"
    if score >= 55: return "NEUTRAL",    "▲▲○"
    if score >= 35: return "DEFENSIVE",  "▲○○"
    return              "PROTECT",    "○○○"

def get_sector_rotation(prices):
    growth_up    = sum(1 for t in ["QQQ","SOXX","NVDA"] if (prices.get(t,{}).get("current") or 0) > (prices.get(t,{}).get("prev") or 0))
    defensive_up = sum(1 for t in ["XLV","IAU"]         if (prices.get(t,{}).get("current") or 0) > (prices.get(t,{}).get("prev") or 0))
    if growth_up >= 2 and defensive_up <= 1:   return "RISK-ON",       "Growth leading. Capital moving into tech/semis."
    if defensive_up >= 2 and growth_up <= 1:   return "RISK-OFF",      "Defensives leading. Rotation out of growth."
    return                                      "MIXED",         "No clear rotation. Selective market."

def get_sentiment_score(prices, macro):
    bullish, bearish = 0, 0
    spy_chg = prices.get("SPY",{})
    if spy_chg.get("current") and spy_chg.get("prev"):
        if (spy_chg["current"] or 0) > (spy_chg["prev"] or 0): bullish += 2
        else: bearish += 2

    vix = macro.get("^VIX",{}).get("current")
    if vix:
        if vix < 18: bullish += 1
        elif vix > 25: bearish += 2
        else: bearish += 1

    oil = macro.get("CL=F",{}).get("change", 0)
    if oil > 2:    bearish += 1
    elif oil < -2: bullish += 1

    yld = macro.get("^TNX",{}).get("change", 0)
    if yld > 0.1:  bearish += 1
    elif yld < -0.1: bullish += 1

    btc = prices.get("BTC-USD",{})
    if btc.get("current") and btc.get("prev"):
        if (btc["current"] or 0) > (btc["prev"] or 0): bullish += 1
        else: bearish += 1

    net = bullish - bearish
    if net >= 3:    return bullish, bearish, "BULLISH",          "#22c55e"
    if net >= 1:    return bullish, bearish, "SLIGHTLY BULLISH", "#86efac"
    if net == 0:    return bullish, bearish, "NEUTRAL",          "#c9a84c"
    if net >= -2:   return bullish, bearish, "SLIGHTLY BEARISH", "#f97316"
    return              bullish, bearish, "BEARISH",          "#ef4444"

# ============================================================
# BUILD EMAIL BODY
# ============================================================
def build_recap(recap_type, prices, macro, news):
    la_tz = pytz.timezone(TIMEZONE)
    now = datetime.now(la_tz)
    date_str = now.strftime("%A, %B %d, %Y · %I:%M %p PT")

    score = calc_market_score(prices)
    dial_label, dial_bars = get_risk_dial(score)
    rotation_label, rotation_desc = get_sector_rotation(prices)
    bull, bear, sentiment_label, sent_color = get_sentiment_score(prices, macro)

    titles = {
        "morning": "🌅 MORNING MARKET BRIEFING — PRE-MARKET STRATEGY",
        "midday":  "⏱️ MIDDAY MARKET UPDATE — REAL-TIME ADJUSTMENT",
        "close":   "🌇 AFTER-MARKET RECAP — STRATEGIC REVIEW",
    }
    title = titles.get(recap_type, "📊 MARKET RECAP")

    SEP = "━" * 52

    lines = [
        title,
        date_str,
        SEP,
        "",

        # ── (0) BREAKING NEWS ──────────────────────────
        "(0) 🚨 BREAKING NEWS RADAR",
        SEP,
    ]

    if news:
        for i, item in enumerate(news[:6], 1):
            lines.append(f"  {i}. {item['title']}")
            lines.append(f"     Source: {item['source']}")
            lines.append("")
    else:
        lines.append("  No headlines retrieved at this time.")
        lines.append("")

    # ── (1) MACRO DRIVERS ──────────────────────────────
    lines += [
        "(1) 🌍 MACRO DRIVERS",
        SEP,
    ]

    macro_map = [
        ("CL=F",      "🛢  Oil (WTI)"),
        ("^TNX",      "📉 10Y Yield"),
        ("DX-Y.NYB",  "💵 US Dollar"),
        ("GC=F",      "🪙 Gold"),
        ("^VIX",      "😨 VIX Fear"),
    ]
    for ticker, label in macro_map:
        m = macro.get(ticker, {})
        val = m.get("current")
        chg = m.get("change", 0)
        if val:
            arrow = "▲" if chg >= 0 else "▼"
            lines.append(f"  {label:<20} ${val:>8.2f}   {arrow} {abs(chg):.2f}%")
        else:
            lines.append(f"  {label:<20} N/A")

    # Bitcoin macro read
    btc = prices.get("BTC-USD", {})
    if btc.get("current") and btc.get("prev"):
        btc_chg = ((btc["current"] - btc["prev"]) / btc["prev"]) * 100
        arrow = "▲" if btc_chg >= 0 else "▼"
        lines.append(f"  {'₿  Bitcoin':<20} ${btc['current']:>8,.0f}   {arrow} {abs(btc_chg):.2f}%")

    # Macro bias
    vix_val = macro.get("^VIX", {}).get("current", 20)
    if vix_val:
        if vix_val < 18:   bias = "→ BIAS: Calm market. Risk appetite intact."
        elif vix_val < 25: bias = "→ BIAS: Mild uncertainty. Stay selective."
        else:              bias = "→ BIAS: Elevated fear. Defensive posture."
        lines.append(f"\n  {bias}")
    lines.append("")

    # ── (2) SENTIMENT SCORE ────────────────────────────
    lines += [
        "(2) ⚖️  SENTIMENT SCORE",
        SEP,
        f"  Bullish signals:  {bull}",
        f"  Bearish signals:  {bear}",
        f"  Overall tone:     {sentiment_label}",
        "",
    ]

    # ── (3) ECONOMIC CALENDAR ──────────────────────────
    lines += [
        "(3) 📅 ECONOMIC CALENDAR",
        SEP,
        "  Check today's schedule at: economiccalendar.com",
        "  Key events to watch: Fed speakers · CPI · Jobs · Auctions",
        "",
    ]

    # ── (4) SECTOR ROTATION ────────────────────────────
    lines += [
        "(4) 🔄 SECTOR ROTATION",
        SEP,
    ]

    sectors = [
        ("Growth (QQQ/SOXX/NVDA)", ["QQQ","SOXX","NVDA"]),
        ("Defensive (XLV/IAU)",    ["XLV","IAU"]),
        ("Cyclical (XLI/KBWB)",    ["XLI","KBWB"]),
        ("Risk (MU/BTC)",          ["MU","BTC-USD"]),
    ]
    for sector_name, tickers in sectors:
        ups = sum(1 for t in tickers if (prices.get(t,{}).get("current") or 0) > (prices.get(t,{}).get("prev") or 0))
        icon = "🟢" if ups == len(tickers) else "🔴" if ups == 0 else "🟡"
        lines.append(f"  {icon} {sector_name}")

    lines += [f"  → {rotation_label}: {rotation_desc}", ""]

    # ── (5) HOLDINGS GAME PLAN ─────────────────────────
    lines += [
        "(5) 📊 HOLDINGS GAME PLAN",
        SEP,
    ]

    total_value = 0
    for h in HOLDINGS:
        p = prices.get(h["ticker"], {})
        current = p.get("current")
        prev    = p.get("prev")
        if not current:
            lines.append(f"  {h['ticker']:<6} — Price unavailable")
            lines.append("")
            continue

        display_ticker = "BTC" if h["ticker"] == "BTC-USD" else h["ticker"]
        pct_avg = ((current - h["avg"]) / h["avg"]) * 100
        pct_day = ((current - prev) / prev * 100) if prev else 0
        dca_label, _ = get_dca_status(current, h["s1"], h["s2"], h["r1"])
        value = current * h["shares"]
        total_value += value

        arrow_avg = "▲" if pct_avg >= 0 else "▼"
        arrow_day = "▲" if pct_day >= 0 else "▼"

        fmt_price = f"${current:,.2f}" if h["ticker"] == "BTC-USD" else f"${current:.2f}"
        fmt_avg   = f"${h['avg']:,.2f}" if h["ticker"] == "BTC-USD" else f"${h['avg']:.2f}"
        fmt_s1    = f"${h['s1']:,.0f}"  if h["ticker"] == "BTC-USD" else f"${h['s1']}"
        fmt_s2    = f"${h['s2']:,.0f}"  if h["ticker"] == "BTC-USD" else f"${h['s2']}"
        fmt_r1    = f"${h['r1']:,.0f}"  if h["ticker"] == "BTC-USD" else f"${h['r1']}"

        lines += [
            f"  {display_ticker} — {h['role']}",
            f"  Price: {fmt_price}  {arrow_day} {abs(pct_day):.2f}% today  |  Avg Cost: {fmt_avg}  {arrow_avg} {abs(pct_avg):.2f}%",
            f"  S2: {fmt_s2}  ·  S1: {fmt_s1}  ·  R1: {fmt_r1}",
            f"  Status: {dca_label}",
            "",
        ]

    lines += [
        f"  PORTFOLIO VALUE: ${total_value:,.2f}",
        "",
    ]

    # ── (6) OPTIONS FLOW NOTE ──────────────────────────
    lines += [
        "(6) 🧾 OPTIONS FLOW",
        SEP,
        "  Check live options flow at: unusualwhales.com or finviz.com",
        f"  VIX at {macro.get('^VIX',{}).get('current','N/A')} → " +
        ("Low hedging. Institutions comfortable." if vix_val and vix_val < 20
         else "Active hedging. Institutions cautious." if vix_val and vix_val < 28
         else "Heavy hedging. Smart money defensive."),
        "",
    ]

    # ── (7) RISK DIAL ──────────────────────────────────
    lines += [
        "(7) 🎯 RISK DIAL",
        SEP,
        f"  Market Score:  {score}/100",
        f"  Posture:       {dial_label}  {dial_bars}",
        f"  Sentiment:     {sentiment_label}",
        f"  Rotation:      {rotation_label}",
        "",
    ]

    # ── (8) ACTION PLAN ────────────────────────────────
    lines += [
        "(8) ✅ ACTION PLAN",
        SEP,
    ]

    # Dynamic action plan based on score
    near_s1 = [h for h in HOLDINGS if prices.get(h["ticker"],{}).get("current") and
               ((prices[h["ticker"]]["current"] - h["s1"]) / prices[h["ticker"]]["current"]) * 100 <= 2.5]
    at_danger = [h for h in HOLDINGS if prices.get(h["ticker"],{}).get("current") and
                 prices[h["ticker"]]["current"] < h["s2"]]

    if score >= 70:
        lines.append("  → Market confirmed strength. Scale into positions near S1.")
        lines.append("  → DCA targets today if near support:")
    elif score >= 50:
        lines.append("  → Controlled buying only. Buy near S1, not at current prices.")
        lines.append("  → Potential DCA targets:")
    elif score >= 35:
        lines.append("  → WAIT mode. Let levels come to you. No chasing.")
        lines.append("  → Watch these levels:")
    else:
        lines.append("  → PROTECT capital. Reduce exposure. No new entries.")
        lines.append("  → Danger zones:")

    if near_s1:
        for h in near_s1[:3]:
            display = "BTC" if h["ticker"] == "BTC-USD" else h["ticker"]
            current = prices[h["ticker"]]["current"]
            fmt = f"${current:,.0f}" if h["ticker"] == "BTC-USD" else f"${current:.2f}"
            lines.append(f"     • {display} at {fmt} — near S1 ${h['s1']:,}")
    else:
        lines.append("     • No holdings currently at S1 buy zones")

    if at_danger:
        lines.append("\n  ⚠️  DANGER — These broke below S2:")
        for h in at_danger:
            display = "BTC" if h["ticker"] == "BTC-USD" else h["ticker"]
            lines.append(f"     🔴 {display} — DO NOT ADD")

    lines += [
        "",
        SEP,
        "Automated Market Recap · Julio's Portfolio System",
        "Data: Yahoo Finance · Reuters RSS · MarketWatch RSS",
        "Cost: $0.00 · Runs free forever",
        SEP,
    ]

    return "\n".join(lines)

# ============================================================
# BUILD HTML EMAIL
# ============================================================
def build_html(plain_text, recap_type, score):
    colors = {"morning": "#c9a84c", "midday": "#3b82f6", "close": "#8b5cf6"}
    accent = colors.get(recap_type, "#c9a84c")

    score_color = "#22c55e" if score >= 70 else "#c9a84c" if score >= 50 else "#f97316" if score >= 35 else "#ef4444"

    html = f"""
<html>
<body style="font-family:'Courier New',monospace; background:#080b10;
             color:#e0e0e0; padding:20px; max-width:660px; margin:0 auto;">
  <div style="border:1px solid {accent}; border-radius:8px;
              padding:16px; margin-bottom:16px; background:#0d1117;">
    <div style="color:{accent}; font-size:10px; letter-spacing:3px; margin-bottom:4px;">
      JULIO'S PORTFOLIO SYSTEM
    </div>
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <div style="font-size:16px; font-weight:bold; color:#fff;">
        {'🌅 MORNING BRIEFING' if recap_type == 'morning' else '⏱️ MIDDAY UPDATE' if recap_type == 'midday' else '🌇 CLOSE RECAP'}
      </div>
      <div style="background:{score_color}20; border:1px solid {score_color};
                  border-radius:6px; padding:4px 12px; text-align:center;">
        <div style="font-size:18px; font-weight:bold; color:{score_color};">{score}</div>
        <div style="font-size:8px; color:{score_color}; letter-spacing:1px;">SCORE</div>
      </div>
    </div>
  </div>
  <div style="border:1px solid #1a1f2e; border-radius:8px; padding:18px; background:#0a0d12;">
    <pre style="white-space:pre-wrap; font-size:12px; line-height:1.8;
                color:#e0e0e0; margin:0; overflow-x:auto;">{plain_text}</pre>
  </div>
  <div style="text-align:center; font-size:10px; color:#333; padding:12px; margin-top:8px;">
    Free automated system · Yahoo Finance + RSS · $0/month
  </div>
</body>
</html>"""
    return html

# ============================================================
# SEND EMAIL
# ============================================================
def send_email(recap_type, body_text, html_body):
    sender   = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")

    subjects = {
        "morning": "🌅 Morning Market Briefing — Pre-Market Strategy",
        "midday":  "⏱️ Midday Market Update — Real-Time Adjustment",
        "close":   "🌇 After-Market Recap — Strategic Review",
    }
    subject = subjects.get(recap_type, "📊 Market Recap")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Market Recap <{sender}>"
    msg["To"]      = RECIPIENT_EMAIL

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, RECIPIENT_EMAIL, msg.as_string())

    print(f"✅ {recap_type.upper()} recap sent to {RECIPIENT_EMAIL}")

# ============================================================
# DETERMINE RECAP TYPE
# ============================================================
def get_recap_type():
    forced = os.environ.get("RECAP_TYPE")
    if forced:
        return forced
    la_tz = pytz.timezone(TIMEZONE)
    now   = datetime.now(la_tz)
    hour, minute = now.hour, now.minute
    if hour == 5:                        return "morning"
    if hour == 7 and minute >= 25:       return "midday"
    if hour == 16:                       return "close"
    return "morning"

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    recap_type = get_recap_type()
    print(f"📊 Running {recap_type.upper()} recap...")

    print("📡 Fetching prices...")
    prices = fetch_prices()

    print("🌍 Fetching macro data...")
    macro = fetch_macro()

    print("📰 Fetching news headlines...")
    news = fetch_news()

    score = calc_market_score(prices)
    print(f"🧠 Market Score: {score}/100")

    print("✍️  Building recap...")
    body = build_recap(recap_type, prices, macro, news)

    html = build_html(body, recap_type, score)

    print("📧 Sending email...")
    send_email(recap_type, body, html)

    print("✅ Done.")
