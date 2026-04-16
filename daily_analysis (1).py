import yfinance as yf
import smtplib
import os
import json
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
    {"ticker":"SPY",     "name":"S&P 500 ETF",        "avg":673.15, "s1":645,   "s2":635,   "r1":668,   "r2":680,   "role":"anchor",    "targetPct":20},
    {"ticker":"QQQ",     "name":"Invesco QQQ",          "avg":597.57, "s1":580,   "s2":570,   "r1":598,   "r2":610,   "role":"growth",    "targetPct":12},
    {"ticker":"SOXX",    "name":"Semiconductor ETF",    "avg":330.78, "s1":332,   "s2":320,   "r1":358,   "r2":370,   "role":"growth",    "targetPct":9 },
    {"ticker":"AAPL",    "name":"Apple",                "avg":257.30, "s1":248,   "s2":240,   "r1":262,   "r2":272,   "role":"anchor",    "targetPct":12},
    {"ticker":"NVDA",    "name":"Nvidia",               "avg":181.46, "s1":172,   "s2":162,   "r1":190,   "r2":200,   "role":"growth",    "targetPct":13},
    {"ticker":"MU",      "name":"Micron Technology",    "avg":376.93, "s1":370,   "s2":358,   "r1":395,   "r2":408,   "role":"risk",      "targetPct":9 },
    {"ticker":"XLI",     "name":"Industrials SPDR",     "avg":169.10, "s1":160,   "s2":154,   "r1":170,   "r2":176,   "role":"cyclical",  "targetPct":8 },
    {"ticker":"XLV",     "name":"Healthcare SPDR",      "avg":156.27, "s1":143,   "s2":138,   "r1":150,   "r2":155,   "role":"defensive", "targetPct":5 },
    {"ticker":"IAU",     "name":"iShares Gold Trust",   "avg":93.76,  "s1":82,    "s2":78,    "r1":88,    "r2":93,    "role":"hedge",     "targetPct":4 },
    {"ticker":"KBWB",    "name":"KBW Bank ETF",         "avg":80.14,  "s1":76,    "s2":72,    "r1":82,    "r2":86,    "role":"cyclical",  "targetPct":4 },
    {"ticker":"BTC-USD", "name":"Bitcoin",              "avg":71896,  "s1":65000, "s2":60000, "r1":76000, "r2":82000, "role":"risk",      "targetPct":4 },
]

# ============================================================
# FETCH PRICE + TECHNICAL DATA
# ============================================================
def fetch_technicals(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist  = stock.history(period="1y", interval="1d")

        if hist.empty or len(hist) < 50:
            return None

        close = hist["Close"]
        current = float(close.iloc[-1])
        prev    = float(close.iloc[-2]) if len(close) > 1 else current

        # Moving averages
        ma50  = float(close.rolling(50).mean().iloc[-1])  if len(close) >= 50  else None
        ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

        # RSI (14)
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss
        rsi   = float((100 - (100 / (1 + rs))).iloc[-1]) if len(close) >= 15 else 50

        # Volume trend
        vol_recent = float(hist["Volume"].iloc[-5:].mean()) if len(hist) >= 5 else 0
        vol_avg    = float(hist["Volume"].iloc[-20:].mean()) if len(hist) >= 20 else 0
        vol_confirm = vol_recent > vol_avg * 0.9

        # Higher highs / higher lows (last 20 days)
        recent = close.iloc[-20:]
        highs  = [float(recent.iloc[i]) for i in range(0, len(recent), 5)]
        lows   = [float(recent.iloc[i]) for i in range(2, len(recent), 5)]
        higher_highs = len(highs) >= 2 and highs[-1] > highs[0]
        higher_lows  = len(lows)  >= 2 and lows[-1]  > lows[0]
        good_structure = higher_highs and higher_lows

        # 52-week high/low
        high_52w = float(close.rolling(252).max().iloc[-1]) if len(close) >= 252 else float(close.max())
        low_52w  = float(close.rolling(252).min().iloc[-1]) if len(close) >= 252 else float(close.min())

        # Day change
        day_change_pct = ((current - prev) / prev * 100) if prev else 0

        return {
            "current":      round(current, 2),
            "prev":         round(prev, 2),
            "ma50":         round(ma50, 2) if ma50 else None,
            "ma200":        round(ma200, 2) if ma200 else None,
            "rsi":          round(rsi, 1),
            "vol_confirm":  vol_confirm,
            "good_structure": good_structure,
            "higher_highs": higher_highs,
            "higher_lows":  higher_lows,
            "high_52w":     round(high_52w, 2),
            "low_52w":      round(low_52w, 2),
            "day_change_pct": round(day_change_pct, 2),
        }
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None

# ============================================================
# RUN 6-STEP ANALYSIS
# ============================================================
def analyze_holding(holding, tech):
    ticker  = holding["ticker"]
    display = "BTC" if ticker == "BTC-USD" else ticker
    btc     = ticker == "BTC-USD"

    if not tech:
        return {
            "ticker": display, "name": holding["name"],
            "score": 0, "verdict": "UNKNOWN", "error": True,
        }

    price  = tech["current"]
    avg    = holding["avg"]
    s1, s2 = holding["s1"], holding["s2"]
    r1, r2 = holding["r1"], holding["r2"]

    score = 0
    details = {}

    # ── STEP 1: TREND (25pts) ──────────────────────────
    above_ma50  = tech["ma50"]  and price > tech["ma50"]
    above_ma200 = tech["ma200"] and price > tech["ma200"]
    trend_up    = above_ma50 and above_ma200

    if above_ma50:  score += 10
    if above_ma200: score += 8
    if trend_up:    score += 7

    details["trend"] = {
        "above_ma50":  above_ma50,
        "above_ma200": above_ma200,
        "ma50_val":    tech["ma50"],
        "ma200_val":   tech["ma200"],
    }

    # ── STEP 2: STRUCTURE (20pts) ──────────────────────
    above_s1     = price > s1
    above_s2     = price > s2
    good_struct  = tech["good_structure"]

    if good_struct: score += 10
    if above_s1:    score += 10

    details["structure"] = {
        "higher_highs": tech["higher_highs"],
        "higher_lows":  tech["higher_lows"],
        "above_s1":     above_s1,
        "above_s2":     above_s2,
        "dist_to_s1":   round(((price - s1) / price) * 100, 1),
        "dist_to_r1":   round(((r1 - price) / price) * 100, 1),
    }

    # ── STEP 3: MOMENTUM (20pts) ───────────────────────
    rsi = tech["rsi"]
    rsi_oversold = rsi < 35
    rsi_neutral  = 35 <= rsi <= 65
    rsi_overbought = rsi > 70
    vol_confirm  = tech["vol_confirm"]

    if rsi_oversold: score += 15
    elif rsi_neutral: score += 8
    if vol_confirm:   score += 5

    if rsi_oversold:     rsi_label = "OVERSOLD"
    elif rsi_overbought: rsi_label = "OVERBOUGHT"
    else:                rsi_label = "NEUTRAL"

    details["momentum"] = {
        "rsi":          rsi,
        "rsi_label":    rsi_label,
        "vol_confirm":  vol_confirm,
    }

    # ── STEP 4: MARKET CYCLE (20pts) ──────────────────
    pct_from_high = ((price - tech["high_52w"]) / tech["high_52w"]) * 100
    pct_from_low  = ((price - tech["low_52w"])  / tech["low_52w"])  * 100

    if pct_from_high > -10 and trend_up:
        cycle = "Late Uptrend"; cycle_score = 10
    elif pct_from_low < 20 and above_s2:
        cycle = "Early Uptrend"; cycle_score = 20
    elif not above_ma50 and not above_ma200:
        cycle = "Markdown"; cycle_score = 0
    elif above_s2 and not trend_up:
        cycle = "Accumulation"; cycle_score = 15
    elif not above_s2:
        cycle = "Markdown"; cycle_score = 0
    else:
        cycle = "Distribution"; cycle_score = 5

    score += cycle_score
    details["cycle"] = {"phase": cycle, "pct_from_52w_high": round(pct_from_high, 1)}

    # ── STEP 5: RELATIVE STRENGTH (15pts) ─────────────
    pct_vs_avg = ((price - avg) / avg) * 100
    if pct_vs_avg > 5:   rs_score = 15
    elif pct_vs_avg > 0: rs_score = 10
    elif pct_vs_avg > -5: rs_score = 5
    else:                 rs_score = 0

    score += rs_score
    details["relative_strength"] = {
        "pct_vs_avg_cost": round(pct_vs_avg, 2),
        "above_avg_cost":  price >= avg,
    }

    score = min(100, score)

    # ── VERDICT ────────────────────────────────────────
    if not above_s2:
        verdict = "DANGER"
    elif score >= 65 and above_s1 and not rsi_overbought:
        verdict = "BUY"
    elif score >= 40:
        verdict = "WAIT"
    else:
        verdict = "AVOID"

    # ── DCA READINESS ──────────────────────────────────
    dist_s1 = details["structure"]["dist_to_s1"]
    if not above_s2:           dca = "DANGER — Do not add"
    elif dist_s1 <= 1.5:       dca = "AT S1 — Entry ready"
    elif dist_s1 <= 3.5:       dca = "NEAR S1 — Prepare"
    elif price >= r1:           dca = "AT R1 — Consider trim"
    else:                       dca = "WAIT for S1"

    return {
        "ticker":         display,
        "name":           holding["name"],
        "role":           holding["role"],
        "price":          price,
        "avg_cost":       avg,
        "s1": s1, "s2": s2, "r1": r1, "r2": r2,
        "day_change":     tech["day_change_pct"],
        "score":          score,
        "verdict":        verdict,
        "dca":            dca,
        "details":        details,
        "btc":            btc,
        "error":          False,
    }

# ============================================================
# CALCULATE PORTFOLIO MARKET SCORE
# ============================================================
def calc_portfolio_score(results):
    valid = [r for r in results if not r.get("error")]
    if not valid:
        return 0

    above_s1 = sum(1 for r in valid if r["price"] > r["s1"])
    score = round((above_s1 / len(valid)) * 35)

    spy = next((r for r in valid if r["ticker"] == "SPY"), None)
    if spy:
        spy_pct = ((spy["price"] - spy["avg_cost"]) / spy["avg_cost"]) * 100
        score += 25 if spy_pct > 0 else 18 if spy_pct > -3 else 10 if spy_pct > -6 else 4

    qqq  = next((r for r in valid if r["ticker"] == "QQQ"), None)
    soxx = next((r for r in valid if r["ticker"] == "SOXX"), None)
    if qqq and soxx:
        score += 25 if (qqq["price"] > qqq["s1"] and soxx["price"] > soxx["s1"]) else 12

    xlv = next((r for r in valid if r["ticker"] == "XLV"), None)
    if xlv:
        score += 10 if xlv["price"] < xlv["avg_cost"] else 15

    return min(100, score)

# ============================================================
# BUILD EMAIL
# ============================================================
def build_email(results, portfolio_score, changed_verdicts):
    la_tz = pytz.timezone(TIMEZONE)
    now = datetime.now(la_tz)
    date_str = now.strftime("%A, %B %d, %Y · %I:%M %p PT")

    score_label = (
        "AGGRESSIVE" if portfolio_score >= 70 else
        "NEUTRAL"    if portfolio_score >= 55 else
        "DEFENSIVE"  if portfolio_score >= 35 else
        "PROTECT"
    )

    verdict_counts = {}
    for r in results:
        if not r.get("error"):
            verdict_counts[r["verdict"]] = verdict_counts.get(r["verdict"], 0) + 1

    SEP = "━" * 52

    lines = [
        "📊 DAILY STOCK ANALYSIS REPORT",
        date_str,
        SEP,
        f"PORTFOLIO SCORE:  {portfolio_score}/100 — {score_label}",
        f"VERDICTS:         " + " · ".join([f"{k}: {v}" for k,v in verdict_counts.items()]),
        "",
    ]

    # Changed verdicts alert
    if changed_verdicts:
        lines += [
            "⚡ VERDICT CHANGES SINCE YESTERDAY",
            SEP,
        ]
        for change in changed_verdicts:
            lines.append(f"  {change['ticker']}: {change['old']} → {change['new']}")
        lines.append("")

    # Group by verdict
    for verdict_group in ["BUY", "WAIT", "AVOID", "DANGER", "UNKNOWN"]:
        group = [r for r in results if r.get("verdict") == verdict_group and not r.get("error")]
        if not group:
            continue

        icons = {"BUY":"🟢", "WAIT":"🟡", "AVOID":"🔴", "DANGER":"🚨"}
        lines += [
            f"{icons.get(verdict_group,'○')} {verdict_group} ({len(group)})",
            SEP,
        ]

        for r in group:
            btc = r["btc"]
            fmt = lambda v: f"${v:,.0f}" if btc else f"${v:.2f}"
            pct_avg = r["details"]["relative_strength"]["pct_vs_avg_cost"]
            d = r["details"]

            lines += [
                f"  {r['ticker']:<6} {r['name']}",
                f"  Price: {fmt(r['price'])}  ({'+' if r['day_change']>=0 else ''}{r['day_change']:.2f}% today)  |  Score: {r['score']}/100",
                f"  Avg Cost: {fmt(r['avg_cost'])}  ({'+' if pct_avg>=0 else ''}{pct_avg:.1f}% from avg)",
                f"  S1: {fmt(r['s1'])}  ·  S2: {fmt(r['s2'])}  ·  R1: {fmt(r['r1'])}",
                f"  Trend:     MA50 {'✓' if d['trend']['above_ma50'] else '✗'}  |  MA200 {'✓' if d['trend']['above_ma200'] else '✗'}  |  {'Uptrend' if d['trend']['above_ma50'] and d['trend']['above_ma200'] else 'Downtrend'}",
                f"  Structure: HH/HL {'✓' if d['structure']['higher_highs'] else '✗'}  |  Above S1 {'✓' if d['structure']['above_s1'] else '✗'}  |  Dist to S1: {d['structure']['dist_to_s1']}%",
                f"  Momentum:  RSI {d['momentum']['rsi']} ({d['momentum']['rsi_label']})  |  Volume {'✓' if d['momentum']['vol_confirm'] else '✗'}",
                f"  Cycle:     {d['cycle']['phase']}  |  {d['cycle']['pct_from_52w_high']}% from 52w high",
                f"  DCA:       {r['dca']}",
                "",
            ]

    # Action summary
    buy_ready = [r for r in results if r.get("verdict") == "BUY"]
    near_s1   = [r for r in results if not r.get("error") and r["details"]["structure"]["dist_to_s1"] <= 3]
    danger    = [r for r in results if r.get("verdict") == "DANGER"]

    lines += [
        SEP,
        "✅ TODAY'S ACTION SUMMARY",
        SEP,
    ]

    if buy_ready:
        lines.append(f"  🟢 BUY READY:    {', '.join([r['ticker'] for r in buy_ready])}")
    if near_s1:
        lines.append(f"  ⚠️  NEAR S1:      {', '.join([r['ticker'] for r in near_s1])} — prepare DCA capital")
    if danger:
        lines.append(f"  🚨 DANGER ZONE:  {', '.join([r['ticker'] for r in danger])} — do NOT add")

    lines += [
        "",
        f"  Portfolio Score: {portfolio_score}/100 → {score_label}",
        "",
        SEP,
        "Automated Analysis · Julio's Portfolio System",
        "Data: Yahoo Finance · 6-Step Framework · $0/month",
        SEP,
    ]

    plain_text = "\n".join(lines)

    # HTML email
    verdict_colors = {"BUY":"#22c55e","WAIT":"#c9a84c","AVOID":"#ef4444","DANGER":"#7f1d1d","UNKNOWN":"#6b7280"}
    score_color = "#22c55e" if portfolio_score>=70 else "#c9a84c" if portfolio_score>=55 else "#f97316" if portfolio_score>=35 else "#ef4444"

    holding_rows = ""
    for r in results:
        if r.get("error"):
            continue
        btc = r["btc"]
        fmt = lambda v: f"${v:,.0f}" if btc else f"${v:.2f}"
        pct_avg = r["details"]["relative_strength"]["pct_vs_avg_cost"]
        d = r["details"]
        vc = verdict_colors.get(r["verdict"], "#6b7280")

        holding_rows += f"""
        <div style="border-left:3px solid {vc}; background:#0d1117; padding:12px 14px; margin-bottom:8px; border-radius:0 6px 6px 0;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <div>
              <span style="font-size:14px; font-weight:bold; color:#fff;">{r['ticker']}</span>
              <span style="font-size:10px; color:#475569; margin-left:8px;">{r['name']}</span>
            </div>
            <div style="display:flex; gap:8px; align-items:center;">
              <span style="font-size:11px; color:{vc}; background:{vc}20; padding:2px 8px; border-radius:3px; font-weight:bold;">{r['verdict']}</span>
              <span style="font-size:12px; color:{vc}; font-weight:bold;">{r['score']}/100</span>
            </div>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; margin-bottom:8px;">
            <div style="background:#070a0f; border-radius:4px; padding:6px; text-align:center;">
              <div style="font-size:9px; color:#475569;">PRICE</div>
              <div style="font-size:13px; color:#fff; font-weight:bold;">{fmt(r['price'])}</div>
              <div style="font-size:9px; color:{'#22c55e' if r['day_change']>=0 else '#ef4444'};">{'+' if r['day_change']>=0 else ''}{r['day_change']:.2f}% today</div>
            </div>
            <div style="background:#070a0f; border-radius:4px; padding:6px; text-align:center;">
              <div style="font-size:9px; color:#475569;">VS AVG COST</div>
              <div style="font-size:13px; color:{'#22c55e' if pct_avg>=0 else '#ef4444'}; font-weight:bold;">{'+' if pct_avg>=0 else ''}{pct_avg:.1f}%</div>
              <div style="font-size:9px; color:#475569;">{fmt(r['avg_cost'])} avg</div>
            </div>
            <div style="background:#070a0f; border-radius:4px; padding:6px; text-align:center;">
              <div style="font-size:9px; color:#475569;">CYCLE</div>
              <div style="font-size:11px; color:#c9a84c; font-weight:bold;">{d['cycle']['phase']}</div>
              <div style="font-size:9px; color:#475569;">{d['cycle']['pct_from_52w_high']}% from high</div>
            </div>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:10px; margin-bottom:6px;">
            <div style="color:#475569;">
              MA50: <span style="color:{'#22c55e' if d['trend']['above_ma50'] else '#ef4444'};">{'✓ Above' if d['trend']['above_ma50'] else '✗ Below'}</span>
              &nbsp;·&nbsp;
              MA200: <span style="color:{'#22c55e' if d['trend']['above_ma200'] else '#ef4444'};">{'✓ Above' if d['trend']['above_ma200'] else '✗ Below'}</span>
            </div>
            <div style="color:#475569;">
              RSI: <span style="color:{'#22c55e' if d['momentum']['rsi']<40 else '#ef4444' if d['momentum']['rsi']>70 else '#c9a84c'};">{d['momentum']['rsi']} ({d['momentum']['rsi_label']})</span>
            </div>
          </div>
          <div style="font-size:10px; color:{vc};">→ DCA: {r['dca']}</div>
        </div>"""

    changed_section = ""
    if changed_verdicts:
        changed_section = f"""
        <div style="background:#c9a84c15; border:1px solid #c9a84c40; border-radius:6px; padding:12px; margin-bottom:14px;">
          <div style="font-size:10px; color:#c9a84c; letter-spacing:2px; margin-bottom:6px;">⚡ VERDICT CHANGES TODAY</div>
          {"".join([f'<div style="font-size:11px; color:#fff; margin-bottom:3px;">{c["ticker"]}: <span style="color:#ef4444;">{c["old"]}</span> → <span style="color:#22c55e;">{c["new"]}</span></div>' for c in changed_verdicts])}
        </div>"""

    html = f"""
<html>
<body style="font-family:'Courier New',monospace; background:#080b10; color:#e0e0e0; padding:20px; max-width:660px; margin:0 auto;">

  <div style="border:1px solid #3b82f6; border-radius:8px; padding:14px; margin-bottom:14px; background:#0d1117;">
    <div style="color:#3b82f6; font-size:10px; letter-spacing:3px; margin-bottom:4px;">DAILY STOCK ANALYSIS REPORT</div>
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <div style="font-size:15px; font-weight:bold; color:#fff;">Portfolio Analysis</div>
      <div style="background:{score_color}20; border:1px solid {score_color}; border-radius:6px; padding:4px 12px; text-align:center;">
        <div style="font-size:20px; font-weight:bold; color:{score_color};">{portfolio_score}</div>
        <div style="font-size:8px; color:{score_color}; letter-spacing:1px;">{score_label}</div>
      </div>
    </div>
    <div style="font-size:10px; color:#475569; margin-top:4px;">{date_str}</div>
  </div>

  {changed_section}

  <div style="margin-bottom:14px;">
    {holding_rows}
  </div>

  <div style="border:1px solid #1e2a3a; border-radius:8px; padding:12px; background:#0d1117; margin-bottom:14px;">
    <div style="font-size:10px; color:#c9a84c; letter-spacing:2px; margin-bottom:8px;">TODAY'S ACTION SUMMARY</div>
    {"".join([f'<div style="font-size:11px; color:#22c55e; margin-bottom:3px;">🟢 BUY READY: {", ".join([r["ticker"] for r in buy_ready])}</div>' if buy_ready else ""])}
    {"".join([f'<div style="font-size:11px; color:#c9a84c; margin-bottom:3px;">⚠️ NEAR S1: {", ".join([r["ticker"] for r in near_s1])}</div>' if near_s1 else ""])}
    {"".join([f'<div style="font-size:11px; color:#ef4444; margin-bottom:3px;">🚨 DANGER: {", ".join([r["ticker"] for r in danger])}</div>' if danger else ""])}
  </div>

  <div style="text-align:center; font-size:10px; color:#334155; padding:8px;">
    Automated Analysis · Yahoo Finance · 6-Step Framework · $0/month
  </div>
</body>
</html>"""

    return plain_text, html

# ============================================================
# SEND EMAIL
# ============================================================
def send_email(plain_text, html, changed_count):
    sender   = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")

    flag = "⚡ " if changed_count > 0 else ""
    subject = f"{flag}📊 Daily Portfolio Analysis — {datetime.now(pytz.timezone(TIMEZONE)).strftime('%b %d, %Y')}"
    if changed_count > 0:
        subject += f" ({changed_count} verdict change{'s' if changed_count>1 else ''})"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Portfolio Analysis <{sender}>"
    msg["To"]      = RECIPIENT_EMAIL

    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, RECIPIENT_EMAIL, msg.as_string())

    print(f"✅ Analysis email sent — {changed_count} verdict changes")

# ============================================================
# LOAD / SAVE YESTERDAY'S VERDICTS (for change detection)
# ============================================================
def load_yesterday():
    path = "/tmp/yesterday_verdicts.json"
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except:
        pass
    return {}

def save_today(results):
    path = "/tmp/yesterday_verdicts.json"
    today = {r["ticker"]: r["verdict"] for r in results if not r.get("error")}
    try:
        with open(path, "w") as f:
            json.dump(today, f)
    except:
        pass

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    la_tz = pytz.timezone(TIMEZONE)
    print(f"📊 Running daily analysis — {datetime.now(la_tz).strftime('%B %d, %Y %I:%M %p PT')}")

    yesterday = load_yesterday()
    results = []

    for holding in HOLDINGS:
        display = "BTC" if holding["ticker"] == "BTC-USD" else holding["ticker"]
        print(f"  Analyzing {display}...")
        tech = fetch_technicals(holding["ticker"])
        result = analyze_holding(holding, tech)
        results.append(result)
        print(f"    → Score: {result['score']}/100 · Verdict: {result['verdict']}")

    # Detect verdict changes
    changed_verdicts = []
    for r in results:
        if not r.get("error"):
            old = yesterday.get(r["ticker"])
            if old and old != r["verdict"]:
                changed_verdicts.append({"ticker":r["ticker"], "old":old, "new":r["verdict"]})
                print(f"  ⚡ CHANGE: {r['ticker']} {old} → {r['verdict']}")

    portfolio_score = calc_portfolio_score(results)
    print(f"\n🧠 Portfolio Score: {portfolio_score}/100")
    print(f"⚡ Verdict changes: {len(changed_verdicts)}")

    save_today(results)

    plain_text, html = build_email(results, portfolio_score, changed_verdicts)
    send_email(plain_text, html, len(changed_verdicts))
    print("✅ Done.")
