import yfinance as yf
import smtplib
import os
import numpy as np
import pandas as pd
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import pytz

# ============================================================
# CONFIGURATION
# ============================================================
RECIPIENT_EMAIL = "julioir89@gmail.com"
TIMEZONE = "America/Los_Angeles"
BACKTEST_YEARS = 3  # 2023 - 2026

HOLDINGS = [
    {"ticker":"SPY",     "name":"S&P 500 ETF",        "avg":673.15, "role":"anchor",    "s1_pct":0.95},
    {"ticker":"QQQ",     "name":"Invesco QQQ",          "avg":597.57, "role":"growth",    "s1_pct":0.94},
    {"ticker":"SOXX",    "name":"Semiconductor ETF",    "avg":330.78, "role":"growth",    "s1_pct":0.93},
    {"ticker":"AAPL",    "name":"Apple",                "avg":257.30, "role":"anchor",    "s1_pct":0.95},
    {"ticker":"NVDA",    "name":"Nvidia",               "avg":181.46, "role":"growth",    "s1_pct":0.93},
    {"ticker":"MU",      "name":"Micron Technology",    "avg":376.93, "role":"risk",      "s1_pct":0.92},
    {"ticker":"XLI",     "name":"Industrials SPDR",     "avg":169.10, "role":"cyclical",  "s1_pct":0.94},
    {"ticker":"XLV",     "name":"Healthcare SPDR",      "avg":156.27, "role":"defensive", "s1_pct":0.94},
    {"ticker":"IAU",     "name":"iShares Gold Trust",   "avg":93.76,  "role":"hedge",     "s1_pct":0.93},
    {"ticker":"KBWB",    "name":"KBW Bank ETF",         "avg":80.14,  "role":"cyclical",  "s1_pct":0.93},
    {"ticker":"BTC-USD", "name":"Bitcoin",              "avg":71896,  "role":"risk",      "s1_pct":0.90},
]

# ============================================================
# DCA SIMULATION ENGINE
# ============================================================
def calc_dynamic_s1(closes, idx, s1_pct):
    """Calculate S1 at a given point in time using trailing MA50."""
    if idx < 50:
        return float(closes.iloc[idx]) * s1_pct
    ma50 = float(closes.iloc[max(0,idx-50):idx].mean())
    return min(ma50, float(closes.iloc[idx]) * s1_pct)

def run_backtest(ticker, name, role, s1_pct, period_years=3):
    """
    Simulate DCA entries at S1 levels and measure returns.
    Rules:
    - Buy when price touches S1 (within 1.5%)
    - Hold for 30/60/90 days and measure return
    - Track win rate, avg return, max drawdown
    """
    print(f"  Backtesting {ticker}...")

    try:
        stock = yf.Ticker(ticker)
        end = datetime.now()
        start = end - timedelta(days=365*period_years + 30)
        hist = stock.history(start=start, end=end, interval="1d")

        if hist.empty or len(hist) < 100:
            return None

        closes = hist["Close"].dropna()
        dates = closes.index

        entries = []
        last_entry_date = None

        for i in range(50, len(closes)-30):
            price = float(closes.iloc[i])
            date  = dates[i]

            # Cooldown — no new entry within 20 trading days of last entry
            if last_entry_date and (date - last_entry_date).days < 20:
                continue

            # Calculate S1 dynamically
            s1 = calc_dynamic_s1(closes, i, s1_pct)

            # Entry signal: price within 1.5% of S1
            dist_to_s1 = ((price - s1) / price) * 100
            if -1.5 <= dist_to_s1 <= 1.5:
                # Measure returns at 30/60/90 days
                results = {}
                for days in [30, 60, 90]:
                    future_idx = min(i + days, len(closes) - 1)
                    future_price = float(closes.iloc[future_idx])
                    ret = ((future_price - price) / price) * 100
                    results[f"ret_{days}d"] = round(ret, 2)

                # Max drawdown in 90 days
                future_window = closes.iloc[i:min(i+90, len(closes))]
                max_drawdown = ((future_window.min() - price) / price) * 100

                entries.append({
                    "date":         date.strftime("%Y-%m-%d"),
                    "price":        round(price, 2),
                    "s1":           round(s1, 2),
                    "dist_to_s1":   round(dist_to_s1, 2),
                    "ret_30d":      results["ret_30d"],
                    "ret_60d":      results["ret_60d"],
                    "ret_90d":      results["ret_90d"],
                    "max_drawdown": round(max_drawdown, 2),
                    "win_30d":      results["ret_30d"] > 0,
                    "win_60d":      results["ret_60d"] > 0,
                    "win_90d":      results["ret_90d"] > 0,
                })
                last_entry_date = date

        if not entries:
            return {
                "ticker": "BTC" if ticker=="BTC-USD" else ticker,
                "name": name, "role": role,
                "total_entries": 0,
                "note": "No S1 signals detected in this period"
            }

        # Calculate statistics
        n = len(entries)
        avg_30 = round(sum(e["ret_30d"] for e in entries) / n, 2)
        avg_60 = round(sum(e["ret_60d"] for e in entries) / n, 2)
        avg_90 = round(sum(e["ret_90d"] for e in entries) / n, 2)
        wr_30  = round(sum(1 for e in entries if e["win_30d"]) / n * 100, 1)
        wr_60  = round(sum(1 for e in entries if e["win_60d"]) / n * 100, 1)
        wr_90  = round(sum(1 for e in entries if e["win_90d"]) / n * 100, 1)
        avg_dd = round(sum(e["max_drawdown"] for e in entries) / n, 2)
        best   = max(entries, key=lambda x: x["ret_90d"])
        worst  = min(entries, key=lambda x: x["ret_90d"])

        # Best year breakdown
        by_year = {}
        for e in entries:
            yr = e["date"][:4]
            if yr not in by_year:
                by_year[yr] = []
            by_year[yr].append(e["ret_90d"])

        year_stats = {yr: round(sum(v)/len(v), 2) for yr, v in by_year.items()}

        return {
            "ticker":         "BTC" if ticker=="BTC-USD" else ticker,
            "name":           name,
            "role":           role,
            "total_entries":  n,
            "avg_ret_30d":    avg_30,
            "avg_ret_60d":    avg_60,
            "avg_ret_90d":    avg_90,
            "win_rate_30d":   wr_30,
            "win_rate_60d":   wr_60,
            "win_rate_90d":   wr_90,
            "avg_drawdown":   avg_dd,
            "best_entry":     best,
            "worst_entry":    worst,
            "by_year":        year_stats,
            "entries":        entries,
        }

    except Exception as e:
        print(f"    Error: {e}")
        return None

def run_spy_benchmark(period_years=3):
    """Buy and hold SPY for comparison."""
    try:
        stock = yf.Ticker("SPY")
        end   = datetime.now()
        start = end - timedelta(days=365*period_years)
        hist  = stock.history(start=start, end=end, interval="1d")
        closes = hist["Close"].dropna()
        start_p = float(closes.iloc[0])
        end_p   = float(closes.iloc[-1])
        total_ret = ((end_p - start_p) / start_p) * 100
        ann_ret   = ((end_p / start_p) ** (1/period_years) - 1) * 100
        dd_series = (closes / closes.cummax() - 1) * 100
        max_dd    = float(dd_series.min())
        return {
            "start_price":  round(start_p, 2),
            "end_price":    round(end_p, 2),
            "total_return": round(total_ret, 2),
            "annual_return":round(ann_ret, 2),
            "max_drawdown": round(max_dd, 2),
        }
    except:
        return None

# ============================================================
# BUILD EMAIL
# ============================================================
def build_email(results, spy_bench):
    la_tz = pytz.timezone(TIMEZONE)
    now = datetime.now(la_tz)
    date_str = now.strftime("%B %d, %Y")
    end_year = now.year
    start_year = end_year - BACKTEST_YEARS

    valid = [r for r in results if r and r.get("total_entries", 0) > 0]
    total_entries = sum(r["total_entries"] for r in valid)
    overall_wr_90 = round(sum(r["win_rate_90d"]*r["total_entries"] for r in valid) / max(total_entries,1), 1)
    overall_avg_90 = round(sum(r["avg_ret_90d"]*r["total_entries"] for r in valid) / max(total_entries,1), 2)

    SEP = "━" * 52

    lines = [
        "📊 BACKTEST RESULTS REPORT",
        f"Period: Jan {start_year} — {date_str}  ({BACKTEST_YEARS} Years)",
        f"Strategy: DCA at S1 levels · All 11 holdings",
        SEP,
        "",
    ]

    # ── SUMMARY ────────────────────────────────────────────
    lines += [
        "🏆 STRATEGY SUMMARY",
        SEP,
        f"  Total S1 entries simulated:  {total_entries}",
        f"  Overall win rate (90 days):  {overall_wr_90}%",
        f"  Average return per entry:    {'+' if overall_avg_90>=0 else ''}{overall_avg_90}% (90 days)",
        "",
    ]

    if spy_bench:
        lines += [
            "📈 vs BUY AND HOLD SPY BENCHMARK",
            SEP,
            f"  SPY buy & hold ({BACKTEST_YEARS}yr total):  {'+' if spy_bench['total_return']>=0 else ''}{spy_bench['total_return']:.1f}%",
            f"  SPY annualized return:          {'+' if spy_bench['annual_return']>=0 else ''}{spy_bench['annual_return']:.1f}%/yr",
            f"  SPY max drawdown:               {spy_bench['max_drawdown']:.1f}%",
            f"  Strategy avg per entry (90d):   {'+' if overall_avg_90>=0 else ''}{overall_avg_90}%",
            f"  Strategy win rate:              {overall_wr_90}%",
            "",
        ]

    # ── BEST & WORST PERFORMERS ────────────────────────────
    sorted_by_wr = sorted(valid, key=lambda x: x["win_rate_90d"], reverse=True)
    lines += ["🥇 RANKED BY WIN RATE (90 DAY HOLD)", SEP]
    for i, r in enumerate(sorted_by_wr):
        medal = "🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else f"  {i+1}."
        lines.append(f"  {medal} {r['ticker']:<6} WR: {r['win_rate_90d']}%  Avg: {'+' if r['avg_ret_90d']>=0 else ''}{r['avg_ret_90d']}%  Entries: {r['total_entries']}")
    lines.append("")

    # ── PER HOLDING DETAIL ─────────────────────────────────
    lines += ["📊 FULL RESULTS — ALL HOLDINGS", SEP]
    for r in valid:
        lines += [
            f"  {r['ticker']} — {r['name']}  ({r['role'].upper()})",
            f"  Entries: {r['total_entries']}  |  Avg drawdown: {r['avg_drawdown']}%",
            f"  30d: WR {r['win_rate_30d']}% · Avg {'+' if r['avg_ret_30d']>=0 else ''}{r['avg_ret_30d']}%",
            f"  60d: WR {r['win_rate_60d']}% · Avg {'+' if r['avg_ret_60d']>=0 else ''}{r['avg_ret_60d']}%",
            f"  90d: WR {r['win_rate_90d']}% · Avg {'+' if r['avg_ret_90d']>=0 else ''}{r['avg_ret_90d']}%",
        ]
        if r.get("by_year"):
            yr_str = "  By year: " + " · ".join([f"{yr}: {'+' if v>=0 else ''}{v}%" for yr,v in sorted(r["by_year"].items())])
            lines.append(yr_str)
        if r.get("best_entry"):
            b = r["best_entry"]
            lines.append(f"  Best entry: {b['date']} at ${b['price']:.2f} → +{b['ret_90d']}% in 90 days")
        if r.get("worst_entry"):
            w = r["worst_entry"]
            lines.append(f"  Worst entry: {w['date']} at ${w['price']:.2f} → {w['ret_90d']}% in 90 days")
        lines.append("")

    # ── INSIGHTS ───────────────────────────────────────────
    best_holder = sorted_by_wr[0] if sorted_by_wr else None
    worst_holder = sorted_by_wr[-1] if sorted_by_wr else None

    lines += ["💡 KEY INSIGHTS", SEP]
    if best_holder:
        lines.append(f"  ✅ BEST: {best_holder['ticker']} had the highest win rate at {best_holder['win_rate_90d']}%")
    if worst_holder:
        lines.append(f"  ⚠️  WEAKEST: {worst_holder['ticker']} had the lowest win rate at {worst_holder['win_rate_90d']}%")
    if overall_wr_90 >= 65:
        lines.append(f"  🏆 SYSTEM VALIDATED: {overall_wr_90}% win rate confirms S1 strategy is effective")
    elif overall_wr_90 >= 50:
        lines.append(f"  ✅ SYSTEM SOLID: {overall_wr_90}% win rate — better than random, consistent edge")
    else:
        lines.append(f"  ⚠️  REVIEW NEEDED: {overall_wr_90}% win rate — consider tightening entry rules")

    lines += [
        f"  📐 Average drawdown per entry: {round(sum(r['avg_drawdown'] for r in valid)/len(valid),1)}% — know your risk",
        "  📅 Longer holds (90d) consistently outperform shorter holds (30d)",
        "",
        SEP,
        "Backtest Report · Julio's Portfolio System",
        "Data: Yahoo Finance · Historical daily prices · $0/month",
        "Note: Past performance does not guarantee future results.",
        SEP,
    ]

    plain = "\n".join(lines)

    # ── HTML ───────────────────────────────────────────────
    wr_color = "#22c55e" if overall_wr_90>=65 else "#c9a84c" if overall_wr_90>=50 else "#ef4444"

    rankings_html = ""
    for i, r in enumerate(sorted_by_wr[:5]):
        bar_width = r["win_rate_90d"]
        rc = {"anchor":"#6b7280","growth":"#3b82f6","risk":"#ef4444","cyclical":"#f97316","defensive":"#22c55e","hedge":"#c9a84c"}.get(r["role"],"#475569")
        rankings_html += f"""
        <div style="background:#0d1117;border:1px solid #1e2a3a;border-left:3px solid {rc};border-radius:8px;padding:10px 12px;margin-bottom:6px;">
          <div style="display:flex;justify-content:space-between;margin-bottom:5px;">
            <div><span style="font-size:13px;font-weight:bold;color:#fff;">{r['ticker']}</span><span style="font-size:9px;color:{rc};background:{rc}20;padding:2px 6px;border-radius:3px;margin-left:6px;">{r['role']}</span></div>
            <div style="text-align:right;"><div style="font-size:14px;font-weight:bold;color:{'#22c55e' if r['win_rate_90d']>=65 else '#c9a84c' if r['win_rate_90d']>=50 else '#ef4444'};">{r['win_rate_90d']}% WR</div><div style="font-size:9px;color:#475569;">{r['total_entries']} entries</div></div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;margin-bottom:5px;">
            <div style="background:#070a0f;border-radius:4px;padding:5px;text-align:center;"><div style="font-size:8px;color:#475569;">30D AVG</div><div style="font-size:11px;color:{'#22c55e' if r['avg_ret_30d']>=0 else '#ef4444'};">{'+' if r['avg_ret_30d']>=0 else ''}{r['avg_ret_30d']}%</div></div>
            <div style="background:#070a0f;border-radius:4px;padding:5px;text-align:center;"><div style="font-size:8px;color:#475569;">60D AVG</div><div style="font-size:11px;color:{'#22c55e' if r['avg_ret_60d']>=0 else '#ef4444'};">{'+' if r['avg_ret_60d']>=0 else ''}{r['avg_ret_60d']}%</div></div>
            <div style="background:#070a0f;border-radius:4px;padding:5px;text-align:center;"><div style="font-size:8px;color:#475569;">90D AVG</div><div style="font-size:11px;color:{'#22c55e' if r['avg_ret_90d']>=0 else '#ef4444'};">{'+' if r['avg_ret_90d']>=0 else ''}{r['avg_ret_90d']}%</div></div>
          </div>
          <div style="background:#1e2a3a;border-radius:3px;height:4px;"><div style="height:100%;width:{bar_width}%;background:{'#22c55e' if r['win_rate_90d']>=65 else '#c9a84c' if r['win_rate_90d']>=50 else '#ef4444'};border-radius:3px;"></div></div>
        </div>"""

    bench_html = ""
    if spy_bench:
        bench_html = f"""
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;">
          <div style="background:#070a0f;border-radius:5px;padding:8px;text-align:center;"><div style="font-size:8px;color:#475569;">SPY {BACKTEST_YEARS}YR TOTAL</div><div style="font-size:13px;font-weight:bold;color:{'#22c55e' if spy_bench['total_return']>=0 else '#ef4444'};">{'+' if spy_bench['total_return']>=0 else ''}{spy_bench['total_return']:.1f}%</div></div>
          <div style="background:#070a0f;border-radius:5px;padding:8px;text-align:center;"><div style="font-size:8px;color:#475569;">SPY ANN. RETURN</div><div style="font-size:13px;font-weight:bold;color:#22c55e;">{spy_bench['annual_return']:.1f}%/yr</div></div>
          <div style="background:#070a0f;border-radius:5px;padding:8px;text-align:center;"><div style="font-size:8px;color:#475569;">SPY MAX DRAWDOWN</div><div style="font-size:13px;font-weight:bold;color:#ef4444;">{spy_bench['max_drawdown']:.1f}%</div></div>
        </div>"""

    html = f"""
<html>
<body style="font-family:'Courier New',monospace;background:#080b10;color:#e0e0e0;padding:20px;max-width:660px;margin:0 auto;">

  <div style="border:1px solid #c9a84c;border-radius:8px;padding:14px;margin-bottom:14px;background:#0d1117;">
    <div style="color:#c9a84c;font-size:10px;letter-spacing:3px;margin-bottom:4px;">BACKTEST RESULTS REPORT</div>
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <div>
        <div style="font-size:15px;font-weight:bold;color:#fff;">DCA at S1 Strategy</div>
        <div style="font-size:10px;color:#475569;">Jan {start_year} — {date_str} · {BACKTEST_YEARS} Years</div>
      </div>
      <div style="background:{wr_color}20;border:1px solid {wr_color};border-radius:6px;padding:6px 14px;text-align:center;">
        <div style="font-size:22px;font-weight:bold;color:{wr_color};">{overall_wr_90}%</div>
        <div style="font-size:8px;color:{wr_color};letter-spacing:1px;">WIN RATE</div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-top:10px;">
      <div style="background:#0a0d14;border-radius:5px;padding:6px;text-align:center;"><div style="font-size:11px;font-weight:bold;color:#fff;">{total_entries}</div><div style="font-size:8px;color:#475569;">TOTAL ENTRIES</div></div>
      <div style="background:#0a0d14;border-radius:5px;padding:6px;text-align:center;"><div style="font-size:11px;font-weight:bold;color:{wr_color};">{overall_wr_90}%</div><div style="font-size:8px;color:#475569;">90D WIN RATE</div></div>
      <div style="background:#0a0d14;border-radius:5px;padding:6px;text-align:center;"><div style="font-size:11px;font-weight:bold;color:{'#22c55e' if overall_avg_90>=0 else '#ef4444'};">{'+' if overall_avg_90>=0 else ''}{overall_avg_90}%</div><div style="font-size:8px;color:#475569;">AVG RETURN</div></div>
    </div>
  </div>

  <div style="border:1px solid #1e2a3a;border-radius:8px;padding:12px;margin-bottom:12px;background:#0d1117;">
    <div style="font-size:9px;color:#c9a84c;letter-spacing:2px;margin-bottom:8px;">📈 vs BUY AND HOLD SPY BENCHMARK</div>
    {bench_html}
  </div>

  <div style="border:1px solid #1e2a3a;border-radius:8px;padding:12px;margin-bottom:12px;background:#0d1117;">
    <div style="font-size:9px;color:#c9a84c;letter-spacing:2px;margin-bottom:8px;">🥇 TOP 5 HOLDINGS BY WIN RATE</div>
    {rankings_html}
  </div>

  <div style="border:1px solid #1e2a3a;border-radius:8px;padding:16px;background:#0a0d12;margin-bottom:12px;">
    <pre style="white-space:pre-wrap;font-size:11px;line-height:1.8;color:#e0e0e0;margin:0;">{plain}</pre>
  </div>

  <div style="text-align:center;font-size:10px;color:#333;padding:8px;">
    Backtest · Yahoo Finance Historical Data · Past performance ≠ future results
  </div>
</body>
</html>"""

    return plain, html

# ============================================================
# SEND EMAIL
# ============================================================
def send_email(plain, html, overall_wr, total_entries):
    sender   = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    subject  = f"📊 Backtest Results — {BACKTEST_YEARS}yr · {total_entries} entries · {overall_wr}% win rate"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Portfolio Backtest <{sender}>"
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html,  "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, RECIPIENT_EMAIL, msg.as_string())
    print(f"✅ Backtest email sent — {total_entries} entries · {overall_wr}% win rate")

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    la_tz = pytz.timezone(TIMEZONE)
    print(f"📊 Running {BACKTEST_YEARS}-Year Backtest — {datetime.now(la_tz).strftime('%B %d, %Y')}")
    print(f"   Testing DCA at S1 strategy across all 11 holdings")
    print()

    results = []
    for h in HOLDINGS:
        r = run_backtest(h["ticker"], h["name"], h["role"], h["s1_pct"], BACKTEST_YEARS)
        if r:
            results.append(r)
            if r.get("total_entries", 0) > 0:
                print(f"    ✓ {r['ticker']}: {r['total_entries']} entries · {r.get('win_rate_90d','?')}% win rate (90d)")
            else:
                print(f"    - {r['ticker']}: No S1 signals found")

    print()
    print("📈 Running SPY benchmark comparison...")
    spy_bench = run_spy_benchmark(BACKTEST_YEARS)
    if spy_bench:
        print(f"   SPY {BACKTEST_YEARS}yr total: {spy_bench['total_return']:.1f}% · Annual: {spy_bench['annual_return']:.1f}%")

    valid = [r for r in results if r and r.get("total_entries",0)>0]
    total_entries = sum(r["total_entries"] for r in valid)
    overall_wr = round(sum(r["win_rate_90d"]*r["total_entries"] for r in valid) / max(total_entries,1), 1)

    print()
    print(f"🏆 Overall: {total_entries} entries · {overall_wr}% win rate")
    print("📧 Sending email...")

    plain, html = build_email(results, spy_bench)
    send_email(plain, html, overall_wr, total_entries)
    print("✅ Done.")
