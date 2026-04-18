import yfinance as yf
import smtplib
import os
import feedparser
import numpy as np
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import pytz

# ============================================================
# CONFIGURATION
# ============================================================
RECIPIENT_EMAIL = "julioir89@gmail.com"
TIMEZONE = "America/Los_Angeles"

HOLDINGS = [
    {"ticker":"SPY",     "name":"S&P 500 ETF",        "avg":673.15, "shares":0.22775, "s1_base":675,   "s2_base":665,   "r1_base":735,   "r2_base":775,   "role":"anchor",    "weight":20},
    {"ticker":"QQQ",     "name":"Invesco QQQ",          "avg":597.57, "shares":0.14075, "s1_base":600,   "s2_base":555,   "r1_base":670,   "r2_base":705,   "role":"growth",    "weight":12},
    {"ticker":"SOXX",    "name":"Semiconductor ETF",    "avg":330.78, "shares":0.18441, "s1_base":355,   "s2_base":305,   "r1_base":425,   "r2_base":450,   "role":"growth",    "weight":9 },
    {"ticker":"AAPL",    "name":"Apple",                "avg":257.30, "shares":0.35021, "s1_base":260,   "s2_base":250,   "r1_base":275,   "r2_base":290,   "role":"anchor",    "weight":12},
    {"ticker":"NVDA",    "name":"Nvidia",               "avg":181.46, "shares":0.55107, "s1_base":185,   "s2_base":165,   "r1_base":210,   "r2_base":220,   "role":"growth",    "weight":13},
    {"ticker":"MU",      "name":"Micron Technology",    "avg":376.93, "shares":0.16183, "s1_base":405,   "s2_base":310,   "r1_base":465,   "r2_base":490,   "role":"risk",      "weight":9 },
    {"ticker":"XLI",     "name":"Industrials SPDR",     "avg":169.10, "shares":0.34299, "s1_base":165,   "s2_base":155,   "r1_base":175,   "r2_base":180,   "role":"cyclical",  "weight":8 },
    {"ticker":"XLV",     "name":"Healthcare SPDR",      "avg":156.27, "shares":0.25475, "s1_base":145,   "s2_base":135,   "r1_base":150,   "r2_base":160,   "role":"defensive", "weight":5 },
    {"ticker":"IAU",     "name":"iShares Gold Trust",   "avg":93.76,  "shares":0.30930, "s1_base":87,    "s2_base":82,    "r1_base":98,    "r2_base":103,   "role":"hedge",     "weight":4 },
    {"ticker":"KBWB",    "name":"KBW Bank ETF",         "avg":80.14,  "shares":0.56149, "s1_base":82,    "s2_base":79,    "r1_base":90,    "r2_base":94,    "role":"cyclical",  "weight":4 },
    {"ticker":"BTC-USD", "name":"Bitcoin",              "avg":71896,  "shares":0.00085, "s1_base":70000, "s2_base":65000, "r1_base":79000, "r2_base":83000, "role":"risk",      "weight":4 },
]

MACRO_TICKERS = {
    "^VIX":     "VIX",
    "GC=F":     "Gold",
    "CL=F":     "Oil",
    "^TNX":     "10Y Yield",
    "DX-Y.NYB": "USD Index",
}

NEWS_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY,QQQ,NVDA,AAPL,MU,SOXX,BTC-USD&region=US&lang=en-US",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/reuters/technologyNews",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
]

# ============================================================
# FETCH WEEKLY PRICE DATA
# ============================================================
def fetch_weekly_data():
    """Get current prices + weekly performance for all holdings."""
    results = {}
    for h in HOLDINGS:
        t = h["ticker"]
        display = "BTC" if t == "BTC-USD" else t
        try:
            stock = yf.Ticker(t)
            hist = stock.history(period="1mo", interval="1d")
            if hist.empty:
                continue

            closes = hist["Close"].dropna()
            current = round(float(closes.iloc[-1]), 2)

            # Week performance (5 trading days)
            week_ago = float(closes.iloc[-6]) if len(closes) >= 6 else float(closes.iloc[0])
            week_pct = ((current - week_ago) / week_ago) * 100

            # Month performance
            month_ago = float(closes.iloc[0])
            month_pct = ((current - month_ago) / month_ago) * 100

            # MA levels
            hist_long = stock.history(period="1y", interval="1d")
            closes_long = hist_long["Close"].dropna()
            ma50  = round(float(closes_long.rolling(50).mean().iloc[-1]),2) if len(closes_long)>=50 else current
            ma200 = round(float(closes_long.rolling(200).mean().iloc[-1]),2) if len(closes_long)>=200 else current

            # RSI
            delta = closes_long.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rs    = gain / loss
            rsi   = round(float((100-(100/(1+rs))).iloc[-1]),1)

            # Dynamic S/R
            lows  = hist_long["Low"].dropna().values  if "Low"  in hist_long else closes_long.values
            highs = hist_long["High"].dropna().values if "High" in hist_long else closes_long.values
            recent_lows  = sorted(lows[-30:])[:5]
            recent_highs = sorted(highs[-30:],reverse=True)[:5]
            avg_low  = float(np.mean(recent_lows))
            avg_high = float(np.mean(recent_highs))

            cands_s1 = [x for x in [avg_low, ma50] if x < current*0.99]
            s1 = max(cands_s1) if cands_s1 else h["s1_base"]
            cands_s2 = [x for x in [ma200, min(recent_lows)] if x < s1*0.99]
            s2 = max(cands_s2) if cands_s2 else h["s2_base"]
            cands_r1 = [x for x in [avg_high] if x > current*1.01]
            r1 = min(cands_r1) if cands_r1 else h["r1_base"]

            def clean(v, p):
                if p > 50000: return round(v/500)*500
                if p > 1000:  return round(v/50)*50
                if p > 100:   return round(v/5)*5
                return round(v, 1)

            results[display] = {
                "ticker":    display,
                "name":      h["name"],
                "role":      h["role"],
                "avg":       h["avg"],
                "shares":    h["shares"],
                "current":   current,
                "week_pct":  round(week_pct, 2),
                "month_pct": round(month_pct, 2),
                "pct_avg":   round(((current-h["avg"])/h["avg"])*100, 2),
                "ma50":      ma50,
                "ma200":     ma200,
                "rsi":       rsi,
                "s1":        clean(s1, current),
                "s2":        clean(s2, current),
                "r1":        clean(r1, current),
                "r2":        h["r1_base"],
                "above_ma50":  current > ma50,
                "above_ma200": current > ma200,
                "trend":     "UPTREND" if current>ma50>ma200 else "DOWNTREND" if current<ma50<ma200 else "SIDEWAYS",
                "btc":       t == "BTC-USD",
            }
        except Exception as e:
            print(f"  Error {display}: {e}")
    return results

def fetch_macro():
    macro = {}
    try:
        tickers = list(MACRO_TICKERS.keys())
        data = yf.download(tickers, period="1wk", interval="1d", progress=False, auto_adjust=True)
        for ticker, name in MACRO_TICKERS.items():
            try:
                series = data["Close"][ticker].dropna()
                current = round(float(series.iloc[-1]), 2)
                week_ago = round(float(series.iloc[0]), 2) if len(series)>1 else current
                chg = round(((current-week_ago)/week_ago)*100, 2) if week_ago else 0
                macro[name] = {"current": current, "week_chg": chg}
            except:
                pass
    except Exception as e:
        print(f"Macro error: {e}")
    return macro

# ============================================================
# FETCH WEEKLY NEWS
# ============================================================
def fetch_news():
    headlines = []
    seen = set()
    for url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                title = entry.get("title","").strip()
                if title and title not in seen and len(title)>20:
                    seen.add(title)
                    headlines.append({"title":title,"source":feed.feed.get("title","News")[:20]})
        except:
            pass
        if len(headlines)>=20: break
    return headlines[:15]

# ============================================================
# ANALYSIS ENGINE
# ============================================================
def calc_portfolio_score(data):
    if not data: return 0
    vals = list(data.values())
    above_s1 = sum(1 for h in vals if h["current"]>h["s1"])
    score = round((above_s1/len(vals))*35)
    spy = data.get("SPY",{})
    if spy:
        pct = spy.get("pct_avg",0)
        score += 25 if pct>0 else 18 if pct>-3 else 10 if pct>-6 else 4
    qqq  = data.get("QQQ",{}).get("current",0)>data.get("QQQ",{}).get("s1",9999)
    soxx = data.get("SOXX",{}).get("current",0)>data.get("SOXX",{}).get("s1",9999)
    score += 25 if (qqq and soxx) else 12
    xlv = data.get("XLV",{})
    score += 10 if xlv.get("current",0)<xlv.get("avg",999) else 15
    return min(100, score)

def get_weekly_winners_losers(data):
    vals = [(h["ticker"], h["week_pct"], h["name"]) for h in data.values()]
    vals.sort(key=lambda x: x[1], reverse=True)
    return vals[:3], vals[-3:]

def get_dca_targets(data, score):
    """Holdings near S1 that are good DCA candidates this week."""
    targets = []
    for h in data.values():
        dist = ((h["current"]-h["s1"])/h["current"])*100
        if h["current"] > h["s2"] and dist <= 5 and score >= 40:
            targets.append({
                "ticker": h["ticker"],
                "price":  h["current"],
                "s1":     h["s1"],
                "dist":   round(dist, 1),
                "rsi":    h["rsi"],
                "btc":    h["btc"],
            })
    return sorted(targets, key=lambda x: x["dist"])

def get_weekly_posture(score, macro):
    vix   = macro.get("VIX",    {}).get("current", 20) or 20
    oil   = macro.get("Oil",    {}).get("current", 80) or 80
    yield_val = macro.get("10Y Yield", {}).get("current", 4.3) or 4.3

    if score >= 70 and vix < 20:
        return "AGGRESSIVE", "Scale into S1 positions with confidence. This is a confirmed DCA window."
    elif score >= 55 and vix < 25:
        return "NEUTRAL", "Controlled DCA at S1 zones only. No chasing breakouts."
    elif score >= 35:
        return "DEFENSIVE", "Wait mode. Preserve capital. Let levels come to you."
    else:
        return "PROTECT", "Capital preservation. Zero new entries until score recovers above 45."

def detect_weekly_themes(data, macro):
    themes = []
    vix = macro.get("VIX",{}).get("current",20) or 20
    oil = macro.get("Oil",{}).get("current",80) or 80
    gold = macro.get("Gold",{}).get("current",3000) or 3000
    oil_chg = macro.get("Oil",{}).get("week_chg",0) or 0
    yield_chg = macro.get("10Y Yield",{}).get("week_chg",0) or 0

    if vix > 25:
        themes.append(("⚠️ HIGH FEAR", f"VIX at {vix:.0f} — institutions hedging. WAIT before adding.", "risk"))
    elif vix < 15:
        themes.append(("😴 COMPLACENCY", f"VIX at {vix:.0f} — calm markets. Good DCA conditions but stay disciplined.", "neutral"))

    if oil > 100:
        themes.append(("🛢 OIL ELEVATED", f"Oil at ${oil:.0f} — inflation risk. Pressure on QQQ/NVDA growth valuations.", "bearish"))
    elif oil < 75:
        themes.append(("🛢 OIL RELIEF", f"Oil at ${oil:.0f} — inflation easing. Tailwind for growth stocks.", "bullish"))

    if oil_chg > 5:
        themes.append(("🛢 OIL SPIKE", f"Oil up {oil_chg:.1f}% this week — watch XLI and IAU as hedge.", "bearish"))
    elif oil_chg < -5:
        themes.append(("🛢 OIL DROP", f"Oil down {abs(oil_chg):.1f}% this week — inflation relief signal.", "bullish"))

    if yield_chg > 5:
        themes.append(("📉 YIELDS RISING", f"10Y yield up {yield_chg:.1f}% this week — pressure on growth stocks QQQ/NVDA.", "bearish"))
    elif yield_chg < -5:
        themes.append(("📉 YIELDS FALLING", f"10Y yield down {abs(yield_chg):.1f}% this week — relief for growth stocks.", "bullish"))

    if gold > 4000:
        themes.append(("🪙 GOLD ELEVATED", f"Gold at ${gold:,.0f} — macro stress active. IAU hedge doing its job.", "risk"))

    spy_week = data.get("SPY",{}).get("week_pct",0)
    if spy_week < -3:
        themes.append(("📉 MARKET PULLBACK", f"SPY down {abs(spy_week):.1f}% this week — potential DCA opportunity forming.", "opportunity"))
    elif spy_week > 3:
        themes.append(("📈 MARKET RALLY", f"SPY up {spy_week:.1f}% this week — don't chase, wait for pullback to S1.", "caution"))

    return themes

# ============================================================
# BUILD EMAIL
# ============================================================
def build_email(data, macro, news, score):
    la_tz = pytz.timezone(TIMEZONE)
    now = datetime.now(la_tz)
    date_str = now.strftime("%A, %B %d, %Y")

    # Date range for the week ahead
    next_friday = now + timedelta(days=(4-now.weekday())%7 + (7 if now.weekday()>=4 else 0))
    week_range = f"{now.strftime('%b %d')} — {next_friday.strftime('%b %d, %Y')}"

    posture, posture_desc = get_weekly_posture(score, macro)
    winners, losers = get_weekly_winners_losers(data)
    dca_targets = get_dca_targets(data, score)
    themes = detect_weekly_themes(data, macro)
    total_value = sum(h["shares"]*h["current"] for h in data.values())
    score_color = "#22c55e" if score>=70 else "#c9a84c" if score>=55 else "#f97316" if score>=35 else "#ef4444"

    SEP = "━" * 52

    lines = [
        "📅 WEEKLY STRATEGY REVIEW",
        f"Week of {week_range}",
        SEP,
        "",
    ]

    # ── EXECUTIVE SUMMARY ──────────────────────────────────
    lines += [
        "📋 EXECUTIVE SUMMARY",
        SEP,
        f"  Portfolio Score:   {score}/100",
        f"  Weekly Posture:    {posture}",
        f"  Portfolio Value:   ${total_value:,.2f}",
        f"  Decision:          {posture_desc}",
        "",
    ]

    # ── WEEKLY THEMES ──────────────────────────────────────
    if themes:
        lines += ["🌍 WEEKLY THEMES & MACRO DRIVERS", SEP]
        for label, desc, _ in themes:
            lines += [f"  {label}", f"  {desc}", ""]

    # ── MACRO SCORECARD ────────────────────────────────────
    lines += ["📊 MACRO SCORECARD — WEEK OVER WEEK", SEP]
    for name, vals in macro.items():
        v = vals.get("current", 0)
        chg = vals.get("week_chg", 0)
        arrow = "▲" if chg >= 0 else "▼"
        impact = ""
        if name == "VIX":
            impact = "→ High fear" if v>25 else "→ Calm"
        elif name == "Oil":
            impact = "→ Inflation pressure" if v>100 else "→ Relief"
        elif name == "10Y Yield":
            impact = "→ Pressure on growth" if chg>0.1 else "→ Relief for growth"
        elif name == "Gold":
            impact = "→ Macro stress hedge active" if v>4000 else ""
        lines.append(f"  {name:<16} ${v:>10,.2f}   {arrow} {abs(chg):.2f}% WoW   {impact}")
    lines.append("")

    # ── LAST WEEK PERFORMANCE ─────────────────────────────
    lines += ["📈 LAST WEEK PERFORMANCE", SEP]
    lines.append("  WINNERS:")
    for ticker, pct, name in winners:
        lines.append(f"  ✅  {ticker:<6} {name:<22} {'+' if pct>=0 else ''}{pct:.2f}%")
    lines.append("  LOSERS:")
    for ticker, pct, name in losers:
        lines.append(f"  ❌  {ticker:<6} {name:<22} {'+' if pct>=0 else ''}{pct:.2f}%")
    lines.append("")

    # ── DCA TARGETS THIS WEEK ─────────────────────────────
    lines += ["🎯 DCA TARGETS THIS WEEK", SEP]
    if dca_targets:
        for t in dca_targets[:5]:
            btc = t["btc"]
            fmt = lambda v: f"${v:,.0f}" if btc else f"${v:.2f}"
            rsi_note = "OVERSOLD" if t["rsi"]<35 else "NEUTRAL" if t["rsi"]<70 else "OVERBOUGHT"
            lines += [
                f"  {t['ticker']} — {t['dist']}% from S1",
                f"  Current: {fmt(t['price'])} · S1: {fmt(t['s1'])} · RSI: {t['rsi']} ({rsi_note})",
                f"  → Watch for S1 touch. Deploy capital if score stays above 45.",
                "",
            ]
    else:
        lines += [
            "  No holdings currently within 5% of S1.",
            "  Market may be extended. Wait for pullback before adding.",
            "",
        ]

    # ── FULL HOLDINGS REVIEW ──────────────────────────────
    lines += ["📊 FULL HOLDINGS REVIEW", SEP]
    for display, h in data.items():
        btc = h["btc"]
        fmt = lambda v: f"${v:,.0f}" if btc else f"${v:.2f}"
        trend_arrow = "▲" if h["trend"]=="UPTREND" else "▼" if h["trend"]=="DOWNTREND" else "→"
        dist_s1 = ((h["current"]-h["s1"])/h["current"])*100
        dca_note = "AT S1 — BUY" if dist_s1<=1.5 else "NEAR S1" if dist_s1<=3.5 else "WAIT" if h["current"]>h["s2"] else "DANGER"
        lines += [
            f"  {display} — {h['role'].upper()}",
            f"  Price: {fmt(h['current'])}  Week: {'+' if h['week_pct']>=0 else ''}{h['week_pct']:.1f}%  Month: {'+' if h['month_pct']>=0 else ''}{h['month_pct']:.1f}%",
            f"  vs Avg: {'+' if h['pct_avg']>=0 else ''}{h['pct_avg']:.1f}%  RSI: {h['rsi']}  Trend: {trend_arrow} {h['trend']}",
            f"  S1: {fmt(h['s1'])}  S2: {fmt(h['s2'])}  R1: {fmt(h['r1'])}",
            f"  DCA Status: {dca_note}",
            "",
        ]

    # ── WEEKLY CALENDAR / CATALYSTS ───────────────────────
    lines += ["📅 WEEK AHEAD — KEY CATALYSTS TO WATCH", SEP]
    lines += [
        "  MON: Watch pre-market futures — direction sets tone for week",
        "  TUE: Fed speaker schedule — any rate signals move yields",
        "  WED: Mid-week macro data (ADP, PMI) — inflation check",
        "  THU: Jobless claims — labor market health gauge",
        "  FRI: Any major earnings or end-of-week position squaring",
        "",
        "  📰 KEY THEMES FROM NEWS THIS WEEK:",
    ]
    for item in news[:5]:
        lines.append(f"  • {item['title'][:75]}")
    lines.append("")

    # ── WEEKLY RULES REMINDER ─────────────────────────────
    lines += [
        SEP,
        "📋 THIS WEEK'S RULES REMINDER",
        SEP,
        "  → Only buy at S1. Never chase a move already in progress.",
        "  → Market score must stay above 45 before any new entry.",
        "  → If VIX spikes above 25 mid-week — pause all entries.",
        "  → One DCA decision per holding per week maximum.",
        "  → When in doubt, the answer is always WAIT.",
        "",
        SEP,
        "Weekly Strategy Review · Julio's Portfolio System",
        "Data: Yahoo Finance · Reuters · MarketWatch · $0/month",
        SEP,
    ]

    plain = "\n".join(lines)

    # ── HTML EMAIL ─────────────────────────────────────────
    dca_html = ""
    for t in dca_targets[:4]:
        btc = t["btc"]
        fmt2 = lambda v: f"${v:,.0f}" if btc else f"${v:.2f}"
        rsi_c = "#22c55e" if t["rsi"]<40 else "#ef4444" if t["rsi"]>70 else "#c9a84c"
        dca_html += f"""
        <div style="border-left:3px solid #22c55e;background:rgba(34,197,94,0.08);padding:10px 12px;margin-bottom:6px;border-radius:0 6px 6px 0;">
          <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
            <span style="font-size:14px;font-weight:bold;color:#fff;">{t['ticker']}</span>
            <span style="font-size:11px;color:#22c55e;">{t['dist']}% from S1</span>
          </div>
          <div style="font-size:10px;color:#94a3b8;margin-bottom:3px;">{fmt2(t['price'])} current · S1 {fmt2(t['s1'])}</div>
          <div style="font-size:9px;color:{rsi_c};">RSI: {t['rsi']} · Watch for S1 touch this week</div>
        </div>"""

    if not dca_html:
        dca_html = '<div style="font-size:10px;color:#475569;padding:8px;">No holdings within 5% of S1. Wait for pullback.</div>'

    theme_html = ""
    for label, desc, sentiment in themes[:4]:
        c = "#22c55e" if sentiment=="bullish" else "#ef4444" if sentiment=="bearish" else "#c9a84c" if sentiment=="risk" else "#3b82f6"
        theme_html += f"""
        <div style="border-left:3px solid {c};padding:8px 12px;margin-bottom:6px;background:{c}12;border-radius:0 5px 5px 0;">
          <div style="font-size:10px;font-weight:bold;color:{c};margin-bottom:2px;">{label}</div>
          <div style="font-size:10px;color:#94a3b8;">{desc}</div>
        </div>"""

    holdings_html = ""
    for display, h in data.items():
        btc = h["btc"]
        fmt3 = lambda v: f"${v:,.0f}" if btc else f"${v:.2f}"
        wc = "#22c55e" if h["week_pct"]>=0 else "#ef4444"
        pc = "#22c55e" if h["pct_avg"]>=0 else "#ef4444"
        rc_color = {"anchor":"#6b7280","growth":"#3b82f6","risk":"#ef4444","cyclical":"#f97316","defensive":"#22c55e","hedge":"#c9a84c"}.get(h["role"],"#475569")
        holdings_html += f"""
        <div style="border-left:3px solid {rc_color};background:#0d1117;padding:10px 12px;margin-bottom:6px;border-radius:0 6px 6px 0;">
          <div style="display:flex;justify-content:space-between;margin-bottom:5px;">
            <div><span style="font-size:13px;font-weight:bold;color:#fff;">{display}</span><span style="font-size:9px;color:{rc_color};background:{rc_color}20;padding:2px 6px;border-radius:3px;margin-left:6px;">{h['role']}</span></div>
            <div style="text-align:right;"><div style="font-size:12px;color:#fff;">{fmt3(h['current'])}</div><div style="font-size:9px;color:{wc};">{'+' if h['week_pct']>=0 else ''}{h['week_pct']:.1f}% this week</div></div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:5px;">
            <div style="background:#070a0f;border-radius:4px;padding:5px;text-align:center;"><div style="font-size:8px;color:#475569;">VS AVG</div><div style="font-size:11px;color:{pc};">{'+' if h['pct_avg']>=0 else ''}{h['pct_avg']:.1f}%</div></div>
            <div style="background:#070a0f;border-radius:4px;padding:5px;text-align:center;"><div style="font-size:8px;color:#475569;">RSI</div><div style="font-size:11px;color:{'#22c55e' if h['rsi']<40 else '#ef4444' if h['rsi']>70 else '#c9a84c'};">{h['rsi']}</div></div>
            <div style="background:#070a0f;border-radius:4px;padding:5px;text-align:center;"><div style="font-size:8px;color:#475569;">TREND</div><div style="font-size:10px;color:{'#22c55e' if h['trend']=='UPTREND' else '#ef4444' if h['trend']=='DOWNTREND' else '#c9a84c'};">{'▲' if h['trend']=='UPTREND' else '▼' if h['trend']=='DOWNTREND' else '→'}</div></div>
          </div>
        </div>"""

    html = f"""
<html>
<body style="font-family:'Courier New',monospace;background:#080b10;color:#e0e0e0;padding:20px;max-width:660px;margin:0 auto;">

  <div style="border:1px solid #c9a84c;border-radius:8px;padding:14px;margin-bottom:14px;background:#0d1117;">
    <div style="color:#c9a84c;font-size:10px;letter-spacing:3px;margin-bottom:4px;">WEEKLY STRATEGY REVIEW</div>
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <div>
        <div style="font-size:16px;font-weight:bold;color:#fff;">Week of {week_range}</div>
        <div style="font-size:10px;color:#475569;margin-top:2px;">{date_str}</div>
      </div>
      <div style="background:{score_color}20;border:1px solid {score_color};border-radius:6px;padding:6px 14px;text-align:center;">
        <div style="font-size:22px;font-weight:bold;color:{score_color};">{score}</div>
        <div style="font-size:8px;color:{score_color};letter-spacing:1px;">{posture}</div>
      </div>
    </div>
    <div style="margin-top:10px;background:{score_color}15;border-radius:5px;padding:8px 12px;font-size:11px;color:{score_color};">→ {posture_desc}</div>
  </div>

  <div style="border:1px solid #1e2a3a;border-radius:8px;padding:12px;margin-bottom:12px;background:#0d1117;">
    <div style="font-size:9px;color:#c9a84c;letter-spacing:2px;margin-bottom:8px;">🌍 WEEKLY THEMES</div>
    {theme_html if theme_html else '<div style="font-size:10px;color:#475569;">No dominant macro theme this week.</div>'}
  </div>

  <div style="border:1px solid #1e2a3a;border-radius:8px;padding:12px;margin-bottom:12px;background:#0d1117;">
    <div style="font-size:9px;color:#c9a84c;letter-spacing:2px;margin-bottom:8px;">📊 MACRO SCORECARD</div>
    {" ".join([f'<div style="display:flex;justify-content:space-between;padding:5px 0;border-top:1px solid #1e2a3a;"><span style="font-size:11px;color:#94a3b8;">{n}</span><div><span style="font-size:11px;color:#fff;margin-right:6px;">${v["current"]:,.2f}</span><span style="font-size:9px;color:{"#22c55e" if v["week_chg"]>=0 else "#ef4444"};">{"▲" if v["week_chg"]>=0 else "▼"}{abs(v["week_chg"]):.2f}% WoW</span></div></div>' for n,v in macro.items() if v.get("current")])}
  </div>

  <div style="border:1px solid #1e2a3a;border-radius:8px;padding:12px;margin-bottom:12px;background:#0d1117;">
    <div style="font-size:9px;color:#c9a84c;letter-spacing:2px;margin-bottom:8px;">🎯 DCA TARGETS THIS WEEK</div>
    {dca_html}
  </div>

  <div style="border:1px solid #1e2a3a;border-radius:8px;padding:12px;margin-bottom:12px;background:#0d1117;">
    <div style="font-size:9px;color:#c9a84c;letter-spacing:2px;margin-bottom:8px;">📊 ALL HOLDINGS — WEEKLY REVIEW</div>
    {holdings_html}
  </div>

  <div style="border:1px solid #1e2a3a;border-radius:8px;padding:12px;margin-bottom:12px;background:#0d1117;">
    <div style="font-size:9px;color:#c9a84c;letter-spacing:2px;margin-bottom:8px;">📋 THIS WEEK'S RULES</div>
    <div style="font-size:10px;color:#94a3b8;line-height:1.8;">
      → Only buy at S1. Never chase a move already in progress.<br>
      → Market score must stay above 45 before any new entry.<br>
      → If VIX spikes above 25 mid-week — pause all entries.<br>
      → One DCA decision per holding per week maximum.<br>
      → When in doubt, the answer is always <strong style="color:#c9a84c;">WAIT</strong>.
    </div>
  </div>

  <div style="text-align:center;font-size:10px;color:#333;padding:8px;">
    Weekly Strategy Review · Julio's Portfolio System · $0/month
  </div>
</body>
</html>"""

    return plain, html

# ============================================================
# SEND EMAIL
# ============================================================
def send_email(plain, html, score, posture):
    sender   = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")

    la_tz = pytz.timezone(TIMEZONE)
    now = datetime.now(la_tz)
    subject = f"📅 Weekly Strategy Review — {now.strftime('%b %d')} — Score {score}/100 {posture}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Portfolio Strategy <{sender}>"
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html,  "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, RECIPIENT_EMAIL, msg.as_string())

    print(f"✅ Weekly review sent — Score {score}/100 · {posture}")

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    la_tz = pytz.timezone(TIMEZONE)
    print(f"📅 Running Weekly Strategy Review — {datetime.now(la_tz).strftime('%B %d, %Y')}")

    print("📡 Fetching weekly price data...")
    data = fetch_weekly_data()
    print(f"  Got data for {len(data)} holdings")

    print("🌍 Fetching macro data...")
    macro = fetch_macro()

    print("📰 Fetching news...")
    news = fetch_news()

    score = calc_portfolio_score(data)
    posture, _ = get_weekly_posture(score, macro)
    print(f"🧠 Portfolio Score: {score}/100 · {posture}")

    plain, html = build_email(data, macro, news, score)
    send_email(plain, html, score, posture)
    print("✅ Done.")
