import yfinance as yf
import smtplib
import os
import feedparser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import pytz
import numpy as np
 
# ============================================================
# CONFIGURATION
# ============================================================
RECIPIENT_EMAIL = "julioir89@gmail.com"
TIMEZONE = "America/Los_Angeles"
 
# Base holdings — avg costs and shares never change
# S/R levels are now calculated DYNAMICALLY from live price data
HOLDINGS = [
    {"ticker":"SPY",     "name":"S&P 500 ETF",        "avg":673.15, "shares":0.22775, "role":"anchor",    "sector":"Market Base",   "keywords":["S&P","SPY","market","stocks","equities","index","Fed","rates","recession","inflation","economy"]},
    {"ticker":"QQQ",     "name":"Invesco QQQ",          "avg":597.57, "shares":0.14075, "role":"growth",    "sector":"Growth Engine", "keywords":["Nasdaq","QQQ","tech","technology","growth","AI","software","Microsoft","Meta","Amazon","Google","Alphabet","semiconductor"]},
    {"ticker":"SOXX",    "name":"Semiconductor ETF",    "avg":330.78, "shares":0.18441, "role":"growth",    "sector":"Semi",          "keywords":["semiconductor","chip","SOXX","TSMC","AMD","Intel","Qualcomm","wafer","fab","AI chip","GPU","export","Nvidia"]},
    {"ticker":"AAPL",    "name":"Apple",                "avg":257.30, "shares":0.35021, "role":"anchor",    "sector":"Stability",     "keywords":["Apple","AAPL","iPhone","Mac","iPad","App Store","Tim Cook","services","China","tariff","iOS"]},
    {"ticker":"NVDA",    "name":"Nvidia",               "avg":181.46, "shares":0.55107, "role":"growth",    "sector":"AI Leader",     "keywords":["Nvidia","NVDA","GPU","AI","data center","H100","blackwell","Jensen Huang","chips","export","semiconductor","artificial intelligence"]},
    {"ticker":"MU",      "name":"Micron Technology",    "avg":376.93, "shares":0.16183, "role":"risk",      "sector":"High Beta",     "keywords":["Micron","MU","DRAM","memory","HBM","storage","semiconductor","chip","memory chip"]},
    {"ticker":"XLI",     "name":"Industrials SPDR",     "avg":169.10, "shares":0.34299, "role":"cyclical",  "sector":"Cyclical",      "keywords":["industrial","manufacturing","infrastructure","defense","Boeing","Caterpillar","XLI","spending","tariff","trade","construction"]},
    {"ticker":"XLV",     "name":"Healthcare SPDR",      "avg":156.27, "shares":0.25475, "role":"defensive", "sector":"Defensive",     "keywords":["healthcare","pharma","biotech","hospital","XLV","FDA","Medicare","drug","insurance","UnitedHealth","medical"]},
    {"ticker":"IAU",     "name":"iShares Gold Trust",   "avg":93.76,  "shares":0.30930, "role":"hedge",     "sector":"Macro Hedge",   "keywords":["gold","IAU","GLD","safe haven","inflation","Fed","dollar","geopolitical","war","crisis","commodity","precious metal"]},
    {"ticker":"KBWB",    "name":"KBW Bank ETF",         "avg":80.14,  "shares":0.56149, "role":"cyclical",  "sector":"Banking",       "keywords":["bank","banking","KBWB","JPMorgan","Wells Fargo","interest rate","yield","credit","loan","financial","Fed"]},
    {"ticker":"BTC-USD", "name":"Bitcoin",              "avg":71896,  "shares":0.00085, "role":"risk",      "sector":"Risk Proxy",    "keywords":["Bitcoin","BTC","crypto","cryptocurrency","digital asset","ETF","Coinbase","blockchain","SEC","regulation","crypto market"]},
]
 
MACRO_TICKERS = {
    "^VIX":     "VIX Fear Index",
    "GC=F":     "Gold Futures",
    "CL=F":     "Oil (WTI)",
    "^TNX":     "10Y Treasury Yield",
    "DX-Y.NYB": "US Dollar Index",
}
 
NEWS_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY,QQQ,NVDA,AAPL,MU,SOXX,BTC-USD&region=US&lang=en-US",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/reuters/technologyNews",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
]
 
MACRO_KEYWORDS = {
    "STAGFLATION": ["stagflation","inflation stagnation","high prices slow growth","supply shock"],
    "RECESSION":   ["recession","GDP contraction","economic slowdown","unemployment","jobs report","layoffs","negative growth"],
    "FED/RATES":   ["Federal Reserve","Fed","FOMC","Powell","rate hike","rate cut","interest rate","basis points","monetary policy"],
    "WAR/GEO":     ["war","conflict","Ukraine","Russia","Middle East","Iran","Israel","Gaza","geopolitical","military strike","ceasefire","Strait of Hormuz"],
    "TARIFFS":     ["tariff","trade war","China tariff","import tax","sanctions","supply chain","IEEPA","Section 232"],
    "OIL/ENERGY":  ["oil","crude","OPEC","energy crisis","petroleum","oil price","oil supply"],
    "BANKING":     ["bank failure","credit crisis","liquidity","contagion","default","debt ceiling","SVB"],
}
 
# ============================================================
# DYNAMIC S/R LEVEL CALCULATOR
# Uses actual price history to find real support/resistance
# ============================================================
def calc_dynamic_levels(ticker, current_price, hist):
    """Calculate real S/R levels from price history, not hardcoded values."""
    try:
        if hist is None or len(hist) < 20:
            # Fallback: percentage-based levels
            return {
                "s1": round(current_price * 0.95, 2),
                "s2": round(current_price * 0.90, 2),
                "r1": round(current_price * 1.05, 2),
                "r2": round(current_price * 1.10, 2),
            }
 
        closes = hist["Close"].dropna().values
        highs  = hist["High"].dropna().values  if "High"  in hist else closes
        lows   = hist["Low"].dropna().values   if "Low"   in hist else closes
 
        # MA-based levels (most reliable for trend following)
        ma20  = float(np.mean(closes[-20:])) if len(closes) >= 20 else current_price
        ma50  = float(np.mean(closes[-50:])) if len(closes) >= 50 else current_price
        ma200 = float(np.mean(closes[-200:])) if len(closes) >= 200 else current_price
 
        # Recent swing lows (last 30 days)
        recent_lows  = sorted(lows[-30:])[:5]
        recent_highs = sorted(highs[-30:], reverse=True)[:5]
        avg_swing_low  = float(np.mean(recent_lows))
        avg_swing_high = float(np.mean(recent_highs))
 
        # S1: Closest meaningful support below current price
        # Priority: recent swing low > MA50 > MA20 > 5% below
        candidates_s1 = [x for x in [avg_swing_low, ma50, ma20] if x < current_price * 0.99]
        s1 = round(max(candidates_s1) if candidates_s1 else current_price * 0.95, 2)
 
        # S2: Deeper support
        candidates_s2 = [x for x in [ma200, min(recent_lows)] if x < s1 * 0.99]
        s2 = round(max(candidates_s2) if candidates_s2 else s1 * 0.94, 2)
 
        # R1: Closest meaningful resistance above current price
        candidates_r1 = [x for x in [avg_swing_high, ma20 * 1.03] if x > current_price * 1.01]
        r1 = round(min(candidates_r1) if candidates_r1 else current_price * 1.05, 2)
 
        # R2: Extended resistance target
        r2 = round(r1 * 1.05, 2)
 
        # Round to clean numbers for readability
        def clean(v, price):
            if price > 1000: return round(v / 50) * 50
            if price > 100:  return round(v / 5) * 5
            if price > 10:   return round(v, 1)
            return round(v, 2)
 
        return {
            "s1": clean(s1, current_price),
            "s2": clean(s2, current_price),
            "r1": clean(r1, current_price),
            "r2": clean(r2, current_price),
            "ma20":  round(ma20, 2),
            "ma50":  round(ma50, 2),
            "ma200": round(ma200, 2),
        }
    except Exception as e:
        print(f"Level calc error for {ticker}: {e}")
        return {
            "s1": round(current_price * 0.95, 2),
            "s2": round(current_price * 0.90, 2),
            "r1": round(current_price * 1.05, 2),
            "r2": round(current_price * 1.10, 2),
        }
 
# ============================================================
# TREND ANALYSIS
# ============================================================
def calc_rsi(closes, period=14):
    try:
        import pandas as pd
        s = pd.Series(closes)
        delta = s.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return round(float(rsi.iloc[-1]), 1)
    except:
        return 50.0
 
def get_trend(current, ma20, ma50, ma200):
    if current > ma50 > ma200: return "UPTREND",   "▲"
    if current < ma50 < ma200: return "DOWNTREND", "▼"
    return "SIDEWAYS", "→"
 
def get_next_move(current, levels, trend):
    """Predict next likely price target based on trend."""
    if trend == "UPTREND":
        return f"Next target: R1 ${levels['r1']} → R2 ${levels['r2']}"
    elif trend == "DOWNTREND":
        return f"Watch support: S1 ${levels['s1']} → S2 ${levels['s2']}"
    else:
        return f"Range: ${levels['s1']} — ${levels['r1']}"
 
# ============================================================
# FETCH ALL DATA
# ============================================================
def fetch_all_data():
    """Single batch fetch for all tickers including full history."""
    tickers = [h["ticker"] for h in HOLDINGS]
    all_data = {}
 
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1y", interval="1d")
            if not hist.empty:
                all_data[ticker] = hist
        except Exception as e:
            print(f"Error fetching {ticker}: {e}")
            all_data[ticker] = None
 
    return all_data
 
def extract_prices(all_data):
    prices = {}
    for ticker, hist in all_data.items():
        try:
            if hist is not None and not hist.empty:
                series = hist["Close"].dropna()
                prices[ticker] = {
                    "current": round(float(series.iloc[-1]), 2),
                    "prev":    round(float(series.iloc[-2]), 2) if len(series) > 1 else None,
                }
            else:
                prices[ticker] = {"current": None, "prev": None}
        except:
            prices[ticker] = {"current": None, "prev": None}
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
                macro[ticker] = {"current": None, "change": 0, "name": MACRO_TICKERS[ticker]}
    except Exception as e:
        print(f"Macro error: {e}")
    return macro
 
# ============================================================
# NEWS — PORTFOLIO TAGGED + MACRO NARRATIVE
# ============================================================
def fetch_news(max_items=25):
    headlines = []
    seen = set()
    for url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                title   = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()
                if title and title not in seen and len(title) > 20:
                    seen.add(title)
                    headlines.append({
                        "title":   title,
                        "summary": summary[:400] if summary else "",
                        "source":  feed.feed.get("title", "News"),
                    })
        except Exception as e:
            print(f"Feed error: {e}")
        if len(headlines) >= max_items:
            break
    return headlines[:max_items]
 
def tag_and_analyze_news(headlines):
    """Tag each headline to holdings AND determine impact."""
    results = {"portfolio": [], "general": [], "macro_themes": {}}
 
    # Count macro themes
    all_text = " ".join([h["title"] + " " + h["summary"] for h in headlines]).lower()
    for theme, keywords in MACRO_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw.lower() in all_text)
        if count >= 1:
            results["macro_themes"][theme] = count
 
    # Tag headlines to holdings
    for item in headlines:
        text = (item["title"] + " " + item["summary"]).lower()
 
        # Check which holdings are affected
        affected = []
        for h in HOLDINGS:
            display = "BTC" if h["ticker"] == "BTC-USD" else h["ticker"]
            for kw in h["keywords"]:
                if kw.lower() in text:
                    affected.append(display)
                    break
 
        # Determine sentiment
        bullish_words = ["surge","rally","rise","gain","jump","beat","record","strong","growth","recover","upgrade","buy","positive","boost","soar","outperform","top","beat","profit"]
        bearish_words = ["fall","drop","decline","crash","miss","weak","recession","cut","layoff","loss","downgrade","sell","negative","risk","war","fear","inflation","tariff","ban","restrict","sanction"]
        bull = sum(1 for w in bullish_words if w in text)
        bear = sum(1 for w in bearish_words if w in text)
        sentiment = "BULLISH" if bull > bear else "BEARISH" if bear > bull else "NEUTRAL"
        sent_color = "🟢" if sentiment=="BULLISH" else "🔴" if sentiment=="BEARISH" else "🟡"
 
        item["affected"] = list(set(affected))
        item["sentiment"] = sentiment
        item["sent_icon"] = sent_color
 
        if affected:
            results["portfolio"].append(item)
        else:
            results["general"].append(item)
 
    return results
 
def build_macro_narrative(themes, macro):
    """Plain-English macro interpretation with portfolio implications."""
    lines = []
    vix   = macro.get("^VIX",    {}).get("current", 20) or 20
    oil   = macro.get("CL=F",    {}).get("current", 80) or 80
    oil_c = macro.get("CL=F",    {}).get("change", 0)   or 0
    yld   = macro.get("^TNX",    {}).get("current", 4.3) or 4.3
    yld_c = macro.get("^TNX",    {}).get("change", 0)   or 0
    gold  = macro.get("GC=F",    {}).get("current", 3000) or 3000
    gold_c= macro.get("GC=F",    {}).get("change", 0)   or 0
    usd_c = macro.get("DX-Y.NYB",{}).get("change", 0)   or 0
 
    # State of the economy right now
    lines.append("📰 GLOBAL ECONOMIC PICTURE:")
 
    if "WAR/GEO" in themes:
        lines.append("  → Active conflict (Middle East/Iran) = Strait of Hormuz risk = energy supply disruption")
        lines.append("    IMPACT: IAU ▲ (safe haven) · Oil volatile · QQQ/NVDA pressured by uncertainty")
 
    if "TARIFFS" in themes:
        lines.append("  → Tariff environment: US effective rate ~11% (highest since 1943)")
        lines.append("    IMPACT: AAPL ⚠️ China exposure · XLI mixed (reshoring+) · SOXX export restrictions risk")
 
    if "FED/RATES" in themes:
        if yld_c > 0.05:
            lines.append(f"  → Fed/Rates: 10Y yield rising ({yld:.2f}%) = tighter conditions ahead")
            lines.append("    IMPACT: QQQ/NVDA/SOXX most vulnerable · KBWB mixed · IAU pressure")
        elif yld_c < -0.05:
            lines.append(f"  → Fed/Rates: 10Y yield falling ({yld:.2f}%) = easing conditions")
            lines.append("    IMPACT: QQQ/NVDA/SOXX BULLISH · Growth stocks benefit")
        else:
            lines.append(f"  → Fed: Wait-and-see mode. 10Y yield at {yld:.2f}% (stable)")
            lines.append("    IMPACT: Neutral for all holdings. War + tariffs prevent rate cuts")
 
    if "RECESSION" in themes:
        lines.append("  → Recession signals present: GDP growth slowing globally (IMF: 3.1% 2026)")
        lines.append("    IMPACT: XLV ▲ (defensive) · IAU ▲ · Reduce MU/BTC exposure")
 
    if "STAGFLATION" in themes:
        lines.append("  → STAGFLATION RISK: Slow growth + persistent inflation = worst combo for markets")
        lines.append("    IMPACT: IAU critical hedge · Reduce QQQ/NVDA · XLV outperforms")
 
    # Oil narrative
    if oil > 100:
        lines.append(f"  → Oil at ${oil:.0f} (ELEVATED): Inflation pressure persists → Fed can't cut")
        lines.append("    IMPACT: All growth stocks pressured · IAU supported · XLI mixed")
    elif oil < 80:
        lines.append(f"  → Oil at ${oil:.0f} (FALLING): Inflation relief → Fed can ease → BULLISH for growth")
        lines.append("    IMPACT: QQQ/NVDA/SOXX BULLISH · Dollar weakens = global liquidity improves")
    else:
        lines.append(f"  → Oil at ${oil:.0f}: Manageable range. Not a major market mover right now")
 
    # Dollar
    if usd_c > 0.3:
        lines.append("  → Dollar STRENGTHENING: Headwind for global earnings (AAPL international revenue)")
    elif usd_c < -0.3:
        lines.append("  → Dollar WEAKENING: Tailwind for US multinationals (AAPL, NVDA international)")
 
    # VIX interpretation
    if vix > 25:
        lines.append(f"  → VIX {vix:.0f} (HIGH FEAR): Institutions hedging aggressively. WAIT before adding.")
    elif vix < 18:
        lines.append(f"  → VIX {vix:.0f} (CALM): Market complacent. Normal DCA conditions. Stay disciplined.")
    else:
        lines.append(f"  → VIX {vix:.0f} (MILD ANXIETY): Selective positioning. Focus on strongest setups only.")
 
    # Overall verdict
    lines.append("")
    lines.append("💡 BOTTOM LINE FOR YOUR PORTFOLIO:")
    if "WAR/GEO" in themes and "TARIFFS" in themes:
        lines.append("  Two major macro headwinds active simultaneously (war + tariffs).")
        lines.append("  Growth stocks CAN rally on ceasefire hopes but fundamental pressure remains.")
        lines.append("  Your IAU hedge is doing its job. Keep it. DCA on growth only at confirmed S1 levels.")
    elif "RECESSION" in themes:
        lines.append("  Defensive posture warranted. XLV and IAU are your anchors.")
        lines.append("  Wait for recession fears to peak before adding growth exposure.")
    else:
        lines.append("  No dominant macro crisis. Standard DCA rules apply.")
        lines.append("  Focus on your levels — let the price come to you.")
 
    return lines
 
# ============================================================
# MARKET SCORE — FIXED FORMULA
# ============================================================
def calc_market_score(prices, macro, levels_data):
    """Fixed score that doesn't inflate when everything rallies above old S1."""
    score = 0
 
    # Component 1: Price vs MA50 (30pts) — are holdings in uptrend?
    above_ma50 = 0
    for h in HOLDINGS:
        levels = levels_data.get(h["ticker"], {})
        price  = prices.get(h["ticker"], {}).get("current", 0) or 0
        ma50   = levels.get("ma50", price)
        if price > ma50:
            above_ma50 += 1
    score += round((above_ma50 / len(HOLDINGS)) * 30)
 
    # Component 2: SPY trend (20pts)
    spy_price = prices.get("SPY", {}).get("current") or 0
    spy_ma200 = levels_data.get("SPY", {}).get("ma200", spy_price)
    spy_ma50  = levels_data.get("SPY", {}).get("ma50", spy_price)
    if spy_price > spy_ma200: score += 10
    if spy_price > spy_ma50:  score += 10
 
    # Component 3: Growth leadership (20pts)
    qqq_price  = prices.get("QQQ",  {}).get("current", 0) or 0
    soxx_price = prices.get("SOXX", {}).get("current", 0) or 0
    qqq_ma50   = levels_data.get("QQQ",  {}).get("ma50", qqq_price)
    soxx_ma50  = levels_data.get("SOXX", {}).get("ma50", soxx_price)
    if qqq_price > qqq_ma50:   score += 10
    if soxx_price > soxx_ma50: score += 10
 
    # Component 4: VIX fear gauge (15pts)
    vix = macro.get("^VIX", {}).get("current", 20) or 20
    if vix < 15:   score += 15
    elif vix < 20: score += 10
    elif vix < 25: score += 5
    # >25 = 0pts
 
    # Component 5: Macro stress (15pts)
    oil_c = macro.get("CL=F",  {}).get("change", 0) or 0
    yld_c = macro.get("^TNX",  {}).get("change", 0) or 0
    if oil_c < 2 and yld_c < 0.1:  score += 15
    elif oil_c < 4 and yld_c < 0.2: score += 8
    elif oil_c < 6:                  score += 3
 
    return min(100, score)
 
def get_risk_dial(score):
    if score >= 70: return "AGGRESSIVE", "▲▲▲"
    if score >= 55: return "NEUTRAL",    "▲▲○"
    if score >= 35: return "DEFENSIVE",  "▲○○"
    return              "PROTECT",    "○○○"
 
def get_dca_status(price, levels):
    if price is None: return "N/A", "○"
    s1, s2, r1 = levels.get("s1", 0), levels.get("s2", 0), levels.get("r1", 0)
    if s2 and price <= s2:                                     return "🚨 DANGER — Do NOT add", "🚨"
    if s1 and ((price - s1) / price) * 100 <= 1.5:            return "🟢 AT S1 — BUY ZONE",   "🟢"
    if s1 and ((price - s1) / price) * 100 <= 3.5:            return "⚠️  NEAR S1 — PREPARE",  "⚠️"
    if r1 and price >= r1 * 0.99:                              return "🔵 AT R1 — WATCH TRIM",  "🔵"
    return                                                         "⏳ WAIT for S1",         "⏳"
 
# ============================================================
# BUILD RECAP
# ============================================================
def build_recap(recap_type, prices, macro, all_data, news_data):
    la_tz = pytz.timezone(TIMEZONE)
    now = datetime.now(la_tz)
    date_str = now.strftime("%A, %B %d, %Y · %I:%M %p PT")
 
    # Calculate dynamic levels for all holdings
    levels_data = {}
    for h in HOLDINGS:
        t = h["ticker"]
        price = prices.get(t, {}).get("current") or 0
        hist  = all_data.get(t)
        levels_data[t] = calc_dynamic_levels(t, price, hist)
 
    score = calc_market_score(prices, macro, levels_data)
    dial_label, dial_bars = get_risk_dial(score)
    macro_lines = build_macro_narrative(news_data.get("macro_themes", {}), macro)
 
    titles = {
        "morning": "🌅 MORNING MARKET BRIEFING — PRE-MARKET STRATEGY",
        "midday":  "⏱️  MIDDAY MARKET UPDATE — REAL-TIME ADJUSTMENT",
        "close":   "🌇 AFTER-MARKET RECAP — STRATEGIC REVIEW",
    }
    SEP = "━" * 52
    lines = [titles.get(recap_type, "📊 MARKET RECAP"), date_str, SEP, ""]
 
    # ── SECTION 1: PORTFOLIO-SPECIFIC NEWS ────────────────
    lines += ["(0) 🚨 PORTFOLIO-SPECIFIC NEWS", SEP]
    portfolio_news = news_data.get("portfolio", [])
    general_news   = news_data.get("general", [])
 
    if portfolio_news:
        for item in portfolio_news[:6]:
            holdings_str = " · ".join(item["affected"])
            lines += [
                f"  {item['sent_icon']} [{item['sentiment']}] {item['title']}",
                f"     Source: {item['source']}",
                f"     → Affects your portfolio: {holdings_str}",
                "",
            ]
    else:
        lines += ["  No direct portfolio news at this time.", ""]
 
    if general_news[:2]:
        lines.append("  OTHER MARKET NEWS:")
        for item in general_news[:2]:
            lines += [f"  • {item['title']}", f"    {item['source']}", ""]
 
    # ── SECTION 2: MACRO NARRATIVE ─────────────────────────
    lines += ["", "(A) 🌍 MACRO NARRATIVE & ECONOMIC ANALYSIS", SEP]
    active_themes = list(news_data.get("macro_themes", {}).keys())
    if active_themes:
        lines.append(f"  Active themes: {' · '.join(active_themes[:5])}")
        lines.append("")
    for line in macro_lines:
        lines.append(f"  {line}")
    lines.append("")
 
    # ── SECTION 3: MACRO DRIVERS ───────────────────────────
    lines += ["(1) 📊 MACRO DRIVERS", SEP]
    macro_map = [
        ("CL=F",       "🛢  Oil (WTI)"),
        ("^TNX",       "📉 10Y Yield"),
        ("DX-Y.NYB",   "💵 US Dollar"),
        ("GC=F",       "🪙 Gold"),
        ("^VIX",       "😨 VIX Fear"),
    ]
    for ticker, label in macro_map:
        m   = macro.get(ticker, {})
        val = m.get("current")
        chg = m.get("change", 0) or 0
        if val:
            arrow = "▲" if chg >= 0 else "▼"
            lines.append(f"  {label:<22} ${val:>10,.2f}   {arrow} {abs(chg):.2f}%")
    lines.append("")
 
    # ── SECTION 4: HOLDINGS — LIVE + DYNAMIC LEVELS ────────
    lines += ["(2) 📊 HOLDINGS — LIVE PRICES + DYNAMIC LEVELS", SEP]
    total_value = 0
 
    # Build per-holding news index
    news_index = {}
    for item in portfolio_news:
        for t in item["affected"]:
            if t not in news_index: news_index[t] = []
            news_index[t].append(item)
 
    for h in HOLDINGS:
        t       = h["ticker"]
        display = "BTC" if t == "BTC-USD" else t
        p       = prices.get(t, {})
        current = p.get("current")
        prev    = p.get("prev")
        levels  = levels_data.get(t, {})
        hist    = all_data.get(t)
 
        if not current:
            lines.append(f"  {display} — Data unavailable\n")
            continue
 
        pct_avg = ((current - h["avg"]) / h["avg"]) * 100
        pct_day = ((current - prev) / prev * 100) if prev else 0
        dca_label, _ = get_dca_status(current, levels)
        value   = current * h["shares"]
        total_value += value
        btc     = t == "BTC-USD"
        fmt     = lambda v: f"${v:,.0f}" if btc else f"${v:.2f}"
        arrow_avg = "▲" if pct_avg >= 0 else "▼"
        arrow_day = "▲" if pct_day >= 0 else "▼"
 
        # Trend from MA data
        ma50  = levels.get("ma50", current)
        ma200 = levels.get("ma200", current)
        trend, trend_arrow = get_trend(current, ma50, levels.get("ma20", current), ma200)
        next_move = get_next_move(current, levels, trend)
 
        # RSI
        rsi = 50
        if hist is not None and not hist.empty:
            try:
                rsi = calc_rsi(hist["Close"].dropna().values)
            except:
                pass
 
        lines += [
            f"  {display} — {h['role'].upper()} · {h['sector']}",
            f"  Price: {fmt(current)}  {arrow_day}{abs(pct_day):.2f}% today  |  Avg: {fmt(h['avg'])}  {arrow_avg}{abs(pct_avg):.1f}%",
            f"  Trend: {trend_arrow} {trend}  |  RSI: {rsi}  |  MA50: {fmt(ma50)}  MA200: {fmt(ma200)}",
            f"  S2: {fmt(levels.get('s2',0))}  ·  S1: {fmt(levels.get('s1',0))}  ·  R1: {fmt(levels.get('r1',0))}  ·  R2: {fmt(levels.get('r2',0))}",
            f"  {dca_label}",
            f"  📈 {next_move}",
        ]
 
        # Attach relevant news
        h_news = news_index.get(display, [])
        if h_news:
            lines.append(f"  📰 NEWS: {h_news[0]['sent_icon']} {h_news[0]['title'][:75]}")
 
        lines.append("")
 
    lines += [f"  TOTAL PORTFOLIO VALUE: ${total_value:,.2f}", ""]
 
    # ── SECTION 5: RISK DIAL ───────────────────────────────
    lines += [
        "(3) 🎯 RISK DIAL", SEP,
        f"  Market Score:  {score}/100",
        f"  Posture:       {dial_label}  {dial_bars}",
        f"  Macro themes:  {', '.join(list(news_data.get('macro_themes',{}).keys())[:3]) or 'None dominant'}",
        "",
    ]
 
    # ── SECTION 6: ACTION PLAN ─────────────────────────────
    lines += ["(4) ✅ ACTION PLAN", SEP]
 
    if score >= 70:
        lines.append("  → Market strong. Scale into S1 positions with confidence.")
    elif score >= 50:
        lines.append("  → Controlled DCA only at S1 levels. No chasing.")
    elif score >= 35:
        lines.append("  → WAIT. Let price come to your S1 zones.")
    else:
        lines.append("  → PROTECT capital. No new entries until score recovers.")
 
    near_s1 = [h for h in HOLDINGS if prices.get(h["ticker"],{}).get("current") and
               levels_data.get(h["ticker"],{}).get("s1") and
               0 <= ((prices[h["ticker"]]["current"] - levels_data[h["ticker"]]["s1"]) / prices[h["ticker"]]["current"]) * 100 <= 3]
    if near_s1:
        lines.append(f"  → Near S1 today: {', '.join([('BTC' if h['ticker']=='BTC-USD' else h['ticker']) for h in near_s1[:4]])}")
 
    lines += [
        "",
        SEP,
        "Automated Market Recap · Julio's Portfolio System",
        "Data: Yahoo Finance · Reuters · MarketWatch · Dynamic S/R · $0/month",
        SEP,
    ]
 
    return "\n".join(lines), levels_data, score
 
# ============================================================
# HTML EMAIL
# ============================================================
def build_html(plain_text, recap_type, score, news_data, macro):
    accent = {"morning":"#c9a84c","midday":"#3b82f6","close":"#8b5cf6"}.get(recap_type,"#c9a84c")
    sc     = "#22c55e" if score>=70 else "#c9a84c" if score>=55 else "#f97316" if score>=35 else "#ef4444"
 
    # Portfolio news HTML
    pnews_html = ""
    for item in news_data.get("portfolio",[])[:5]:
        bc = "#22c55e" if item["sentiment"]=="BULLISH" else "#ef4444" if item["sentiment"]=="BEARISH" else "#c9a84c"
        holdings_str = " · ".join(item["affected"])
        pnews_html += f"""
        <div style="border-left:3px solid {bc}; padding:8px 12px; margin-bottom:6px; background:#0d1117; border-radius:0 5px 5px 0;">
          <div style="display:flex; justify-content:space-between; margin-bottom:3px;">
            <span style="font-size:9px; color:{bc}; font-weight:bold;">{item['sentiment']}</span>
            <span style="font-size:9px; color:#475569;">{item['source']}</span>
          </div>
          <div style="font-size:11px; color:#e0e0e0; margin-bottom:3px; line-height:1.4;">{item['title']}</div>
          <div style="font-size:9px; color:#3b82f6;">→ Your holdings: {holdings_str}</div>
        </div>"""
 
    if not pnews_html:
        pnews_html = '<div style="font-size:10px;color:#475569;">No portfolio-specific headlines at this time.</div>'
 
    # Macro themes
    themes_html = " ".join([
        f'<span style="background:#1e2a3a;color:#c9a84c;font-size:9px;padding:3px 8px;border-radius:3px;margin-right:4px;">{t}</span>'
        for t in list(news_data.get("macro_themes",{}).keys())[:5]
    ]) or '<span style="color:#475569;font-size:10px;">No dominant macro theme</span>'
 
    return f"""
<html>
<body style="font-family:'Courier New',monospace;background:#080b10;color:#e0e0e0;padding:20px;max-width:660px;margin:0 auto;">
  <div style="border:1px solid {accent};border-radius:8px;padding:14px;margin-bottom:12px;background:#0d1117;">
    <div style="color:{accent};font-size:10px;letter-spacing:3px;margin-bottom:4px;">JULIO'S PORTFOLIO SYSTEM</div>
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <div style="font-size:15px;font-weight:bold;color:#fff;">
        {'🌅 MORNING' if recap_type=='morning' else '⏱️ MIDDAY' if recap_type=='midday' else '🌇 CLOSE'} BRIEFING
      </div>
      <div style="background:{sc}20;border:1px solid {sc};border-radius:6px;padding:4px 12px;text-align:center;">
        <div style="font-size:20px;font-weight:bold;color:{sc};">{score}</div>
        <div style="font-size:8px;color:{sc};letter-spacing:1px;">SCORE</div>
      </div>
    </div>
  </div>
 
  <div style="border:1px solid #1e2a3a;border-radius:8px;padding:12px;margin-bottom:10px;background:#0d1117;">
    <div style="font-size:9px;color:#c9a84c;letter-spacing:2px;margin-bottom:8px;">🚨 PORTFOLIO NEWS — WHAT AFFECTS YOUR HOLDINGS</div>
    {pnews_html}
  </div>
 
  <div style="border:1px solid #1e2a3a;border-radius:8px;padding:12px;margin-bottom:10px;background:#0d1117;">
    <div style="font-size:9px;color:#c9a84c;letter-spacing:2px;margin-bottom:6px;">🌍 ACTIVE MACRO THEMES</div>
    <div style="margin-bottom:6px;">{themes_html}</div>
    <div style="font-size:10px;color:#475569;line-height:1.6;">
      Oil: ${macro.get("CL=F",{}).get("current","N/A")} &nbsp;·&nbsp;
      10Y Yield: {macro.get("^TNX",{}).get("current","N/A")}% &nbsp;·&nbsp;
      Gold: ${macro.get("GC=F",{}).get("current","N/A"):,} &nbsp;·&nbsp;
      VIX: {macro.get("^VIX",{}).get("current","N/A")}
    </div>
  </div>
 
  <div style="border:1px solid #1e2a3a;border-radius:8px;padding:16px;background:#0a0d12;margin-bottom:10px;">
    <pre style="white-space:pre-wrap;font-size:11px;line-height:1.8;color:#e0e0e0;margin:0;overflow-x:auto;">{plain_text}</pre>
  </div>
 
  <div style="text-align:center;font-size:10px;color:#333;padding:8px;">
    Free automated system · Dynamic S/R Levels · Yahoo Finance + RSS · $0/month
  </div>
</body>
</html>"""
 
# ============================================================
# SEND EMAIL
# ============================================================
def send_email(recap_type, body, html):
    sender   = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    subjects = {
        "morning": "🌅 Morning Briefing — Pre-Market Strategy",
        "midday":  "⏱️  Midday Update — Real-Time Adjustment",
        "close":   "🌇 Close Recap — Strategic Review",
    }
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subjects.get(recap_type, "📊 Market Recap")
    msg["From"]    = f"Market Recap <{sender}>"
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(body,  "plain"))
    msg.attach(MIMEText(html,  "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, RECIPIENT_EMAIL, msg.as_string())
    print(f"✅ {recap_type.upper()} recap sent")
 
# ============================================================
# RECAP TYPE
# ============================================================
def get_recap_type():
    forced = os.environ.get("RECAP_TYPE")
    if forced: return forced
    la_tz = pytz.timezone(TIMEZONE)
    now   = datetime.now(la_tz)
    h, m  = now.hour, now.minute
    if h in [4,5]:          return "morning"
    if h in [6,7] or (h==7 and m>=25): return "midday"
    if h in [15,16]:        return "close"
    return "morning"
 
# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    recap_type = get_recap_type()
    print(f"📊 Running {recap_type.upper()} recap...")
 
    print("📡 Fetching all price history...")
    all_data = fetch_all_data()
    prices   = extract_prices(all_data)
 
    print("🌍 Fetching macro...")
    macro = fetch_macro()
 
    print("📰 Fetching and analyzing news...")
    raw_news  = fetch_news()
    news_data = tag_and_analyze_news(raw_news)
 
    portfolio_count = len(news_data.get("portfolio",[]))
    theme_count     = len(news_data.get("macro_themes",{}))
    print(f"   {portfolio_count} portfolio-specific headlines · {theme_count} macro themes: {list(news_data.get('macro_themes',{}).keys())}")
 
    print("✍️  Building recap...")
    body, levels, score = build_recap(recap_type, prices, macro, all_data, news_data)
    html = build_html(body, recap_type, score, news_data, macro)
 
    print(f"🧠 Market Score: {score}/100")
    print("📧 Sending email...")
    send_email(recap_type, body, html)
    print("✅ Done.")
