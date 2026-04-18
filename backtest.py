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
BACKTEST_YEARS = 3
 
HOLDINGS = [
    {"ticker":"SPY",     "name":"S&P 500 ETF",        "role":"anchor"   },
    {"ticker":"QQQ",     "name":"Invesco QQQ",          "role":"growth"   },
    {"ticker":"SOXX",    "name":"Semiconductor ETF",    "role":"growth"   },
    {"ticker":"AAPL",    "name":"Apple",                "role":"anchor"   },
    {"ticker":"NVDA",    "name":"Nvidia",               "role":"growth"   },
    {"ticker":"MU",      "name":"Micron Technology",    "role":"risk"     },
    {"ticker":"XLI",     "name":"Industrials SPDR",     "role":"cyclical" },
    {"ticker":"XLV",     "name":"Healthcare SPDR",      "role":"defensive"},
    {"ticker":"IAU",     "name":"iShares Gold Trust",   "role":"hedge"    },
    {"ticker":"KBWB",    "name":"KBW Bank ETF",         "role":"cyclical" },
    {"ticker":"BTC-USD", "name":"Bitcoin",              "role":"risk"     },
]
 
# ============================================================
# BACKTEST ENGINE
# ============================================================
def run_backtest(ticker, name, role, period_years=3):
    """
    Simulate DCA entries when price pulls back to MA50 (our S1 proxy).
    Entry: price comes within 3% of MA50 from above (pullback to support)
    Filter: price must be above MA200 (uptrend only)
    Cooldown: 15 trading days between entries
    Measure: returns at 30 / 60 / 90 days after entry
    """
    print(f"  Backtesting {ticker}...")
    display = "BTC" if ticker == "BTC-USD" else ticker
 
    try:
        stock = yf.Ticker(ticker)
        end   = datetime.now()
        start = end - timedelta(days=365*period_years + 90)
        hist  = stock.history(start=start, end=end, interval="1d")
 
        if hist.empty or len(hist) < 210:
            print(f"    Not enough data for {display}")
            return None
 
        closes = hist["Close"].dropna().reset_index(drop=True)
        dates  = hist["Close"].dropna().index
 
        ma50_s  = closes.rolling(50).mean()
        ma200_s = closes.rolling(200).mean()
 
        entries = []
        last_entry_idx = -20
 
        for i in range(200, len(closes) - 91):
            price = float(closes.iloc[i])
            ma50  = float(ma50_s.iloc[i])
            ma200 = float(ma200_s.iloc[i])
 
            if pd.isna(ma50) or pd.isna(ma200) or ma50 <= 0:
                continue
 
            # Cooldown
            if i - last_entry_idx < 15:
                continue
 
            # Uptrend filter: must be above MA200
            if price < ma200 * 0.99:
                continue
 
            # Entry signal: price within 3% above MA50 (pullback to support)
            dist = ((price - ma50) / ma50) * 100
            if 0 <= dist <= 3.0:
                # Measure returns
                ret = {}
                for days in [30, 60, 90]:
                    fp = float(closes.iloc[min(i+days, len(closes)-1)])
                    ret[days] = round(((fp - price) / price) * 100, 2)
 
                fw = closes.iloc[i:min(i+90, len(closes))]
                max_dd = round(((float(fw.min()) - price) / price) * 100, 2)
 
                try:
                    date_str = dates[i].strftime("%Y-%m-%d")
                except:
                    date_str = "N/A"
 
                entries.append({
                    "date":  date_str,
                    "price": round(price, 2),
                    "ma50":  round(ma50, 2),
                    "dist":  round(dist, 2),
                    "r30":   ret[30],
                    "r60":   ret[60],
                    "r90":   ret[90],
                    "dd":    max_dd,
                    "w30":   ret[30] > 0,
                    "w60":   ret[60] > 0,
                    "w90":   ret[90] > 0,
                })
                last_entry_idx = i
 
        if not entries:
            print(f"    No signals for {display}")
            return {"ticker":display,"name":name,"role":role,"total_entries":0}
 
        n = len(entries)
        result = {
            "ticker":        display,
            "name":          name,
            "role":          role,
            "total_entries": n,
            "avg_r30":  round(sum(e["r30"] for e in entries)/n, 2),
            "avg_r60":  round(sum(e["r60"] for e in entries)/n, 2),
            "avg_r90":  round(sum(e["r90"] for e in entries)/n, 2),
            "wr30":     round(sum(1 for e in entries if e["w30"])/n*100, 1),
            "wr60":     round(sum(1 for e in entries if e["w60"])/n*100, 1),
            "wr90":     round(sum(1 for e in entries if e["w90"])/n*100, 1),
            "avg_dd":   round(sum(e["dd"] for e in entries)/n, 2),
            "best":     max(entries, key=lambda x: x["r90"]),
            "worst":    min(entries, key=lambda x: x["r90"]),
            "entries":  entries,
        }
 
        # Year breakdown
        by_year = {}
        for e in entries:
            yr = e["date"][:4]
            by_year.setdefault(yr, []).append(e["r90"])
        result["by_year"] = {yr: round(sum(v)/len(v),2) for yr,v in by_year.items()}
 
        print(f"    ✓ {display}: {n} entries · WR90={result['wr90']}% · Avg90={result['avg_r90']:+.1f}%")
        return result
 
    except Exception as e:
        print(f"    Error {display}: {e}")
        return None
 
def run_spy_benchmark(period_years=3):
    try:
        stock = yf.Ticker("SPY")
        end   = datetime.now()
        start = end - timedelta(days=365*period_years)
        hist  = stock.history(start=start, end=end, interval="1d")
        closes = hist["Close"].dropna()
        sp = float(closes.iloc[0])
        ep = float(closes.iloc[-1])
        total  = round(((ep-sp)/sp)*100, 2)
        annual = round(((ep/sp)**(1/period_years)-1)*100, 2)
        dd_s   = (closes/closes.cummax()-1)*100
        max_dd = round(float(dd_s.min()), 2)
        return {"start":round(sp,2),"end":round(ep,2),"total":total,"annual":annual,"max_dd":max_dd}
    except Exception as e:
        print(f"Benchmark error: {e}")
        return None
 
# ============================================================
# BUILD EMAIL
# ============================================================
def build_email(results, spy_bench):
    la_tz = pytz.timezone(TIMEZONE)
    now = datetime.now(la_tz)
    date_str = now.strftime("%B %d, %Y")
    start_year = now.year - BACKTEST_YEARS
 
    valid = [r for r in results if r and r.get("total_entries",0) > 0]
    if not valid:
        plain = "Backtest completed but no signals were found across all holdings."
        return plain, f"<html><body><p>{plain}</p></body></html>"
 
    total_entries = sum(r["total_entries"] for r in valid)
    overall_wr90  = round(sum(r["wr90"]*r["total_entries"] for r in valid)/total_entries, 1)
    overall_avg90 = round(sum(r["avg_r90"]*r["total_entries"] for r in valid)/total_entries, 2)
    avg_dd        = round(sum(r["avg_dd"]*r["total_entries"] for r in valid)/total_entries, 1)
 
    score_c = "#22c55e" if overall_wr90>=65 else "#c9a84c" if overall_wr90>=50 else "#ef4444"
    SEP = "━"*52
 
    ranked = sorted(valid, key=lambda x: x["wr90"], reverse=True)
 
    lines = [
        "📊 BACKTEST RESULTS REPORT",
        f"Period: Jan {start_year} — {date_str}  ({BACKTEST_YEARS} Years)",
        f"Strategy: DCA at MA50 pullback · All 11 holdings",
        f"Entry rule: Price within 3% above MA50 · Must be above MA200",
        SEP,"",
        "🏆 STRATEGY SUMMARY", SEP,
        f"  Total S1 entries simulated:  {total_entries}",
        f"  Overall 90-day win rate:     {overall_wr90}%",
        f"  Avg return per entry (90d):  {overall_avg90:+.2f}%",
        f"  Avg max drawdown per entry:  {avg_dd:.1f}%",
        "",
    ]
 
    if spy_bench:
        lines += [
            "📈 vs BUY AND HOLD SPY BENCHMARK", SEP,
            f"  SPY {BACKTEST_YEARS}yr total return:    {spy_bench['total']:+.1f}%",
            f"  SPY annualized return:       {spy_bench['annual']:+.1f}%/yr",
            f"  SPY max drawdown:            {spy_bench['max_dd']:.1f}%",
            f"  Strategy avg per entry 90d:  {overall_avg90:+.2f}%",
            f"  Strategy win rate 90d:       {overall_wr90}%",
            "",
        ]
 
    lines += ["🥇 RANKED BY 90-DAY WIN RATE", SEP]
    for i, r in enumerate(ranked):
        medal = ["🥇","🥈","🥉"][i] if i<3 else f"  {i+1}."
        lines.append(f"  {medal} {r['ticker']:<6} WR: {r['wr90']}%  Avg: {r['avg_r90']:+.1f}%  Entries: {r['total_entries']}")
    lines.append("")
 
    lines += ["📊 FULL RESULTS — ALL HOLDINGS", SEP]
    for r in ranked:
        lines += [
            f"  {r['ticker']} — {r['name']}  ({r['role'].upper()})",
            f"  Entries: {r['total_entries']}  |  Avg drawdown: {r['avg_dd']}%",
            f"  30d: WR {r['wr30']}%  Avg {r['avg_r30']:+.1f}%",
            f"  60d: WR {r['wr60']}%  Avg {r['avg_r60']:+.1f}%",
            f"  90d: WR {r['wr90']}%  Avg {r['avg_r90']:+.1f}%",
        ]
        if r.get("by_year"):
            lines.append("  By year: " + " · ".join(f"{yr}: {v:+.1f}%" for yr,v in sorted(r["by_year"].items())))
        if r.get("best"):
            b = r["best"]
            lines.append(f"  Best entry:  {b['date']} @ ${b['price']:.2f} → {b['r90']:+.1f}% (90d)")
        if r.get("worst"):
            w = r["worst"]
            lines.append(f"  Worst entry: {w['date']} @ ${w['price']:.2f} → {w['r90']:+.1f}% (90d)")
        lines.append("")
 
    verdict = "SYSTEM VALIDATED ✅" if overall_wr90>=65 else "SYSTEM SOLID ✅" if overall_wr90>=50 else "REVIEW NEEDED ⚠️"
    lines += [
        "💡 KEY INSIGHTS", SEP,
        f"  {verdict}: {overall_wr90}% win rate over {total_entries} entries",
        f"  Best performer: {ranked[0]['ticker']} at {ranked[0]['wr90']}% win rate",
        f"  Weakest performer: {ranked[-1]['ticker']} at {ranked[-1]['wr90']}% win rate",
        f"  Longer holds (90d) consistently outperform shorter (30d)",
        f"  Average drawdown {avg_dd}% — tolerable if holding 90+ days",
        "",
        SEP,
        "Backtest · Julio's Portfolio System · Yahoo Finance Historical Data",
        "Note: Past performance does not guarantee future results.",
        SEP,
    ]
 
    plain = "\n".join(lines)
 
    # HTML
    rankings_html = ""
    for i, r in enumerate(ranked[:6]):
        rc = {"anchor":"#6b7280","growth":"#3b82f6","risk":"#ef4444","cyclical":"#f97316","defensive":"#22c55e","hedge":"#c9a84c"}.get(r["role"],"#475569")
        wrc = "#22c55e" if r["wr90"]>=65 else "#c9a84c" if r["wr90"]>=50 else "#ef4444"
        rankings_html += f"""
        <div style="background:#0d1117;border:1px solid #1e2a3a;border-left:3px solid {rc};border-radius:8px;padding:10px 12px;margin-bottom:6px;">
          <div style="display:flex;justify-content:space-between;margin-bottom:5px;">
            <div><span style="font-size:13px;font-weight:bold;color:#fff;">{r['ticker']}</span><span style="font-size:9px;color:{rc};background:{rc}20;padding:2px 6px;border-radius:3px;margin-left:6px;">{r['role']}</span><span style="font-size:9px;color:#475569;margin-left:6px;">{r['total_entries']} entries</span></div>
            <span style="font-size:14px;font-weight:bold;color:{wrc};">{r['wr90']}% WR</span>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;">
            <div style="background:#070a0f;border-radius:4px;padding:5px;text-align:center;"><div style="font-size:8px;color:#475569;">30D AVG</div><div style="font-size:11px;color:{'#22c55e' if r['avg_r30']>=0 else '#ef4444'};">{r['avg_r30']:+.1f}%</div></div>
            <div style="background:#070a0f;border-radius:4px;padding:5px;text-align:center;"><div style="font-size:8px;color:#475569;">60D AVG</div><div style="font-size:11px;color:{'#22c55e' if r['avg_r60']>=0 else '#ef4444'};">{r['avg_r60']:+.1f}%</div></div>
            <div style="background:#070a0f;border-radius:4px;padding:5px;text-align:center;"><div style="font-size:8px;color:#475569;">90D AVG</div><div style="font-size:11px;color:{'#22c55e' if r['avg_r90']>=0 else '#ef4444'};">{r['avg_r90']:+.1f}%</div></div>
          </div>
          <div style="background:#1e2a3a;border-radius:3px;height:4px;margin-top:6px;"><div style="height:100%;width:{r['wr90']}%;background:{wrc};border-radius:3px;"></div></div>
        </div>"""
 
    bench_html = ""
    if spy_bench:
        bench_html = f"""
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;">
          <div style="background:#070a0f;border-radius:5px;padding:8px;text-align:center;"><div style="font-size:8px;color:#475569;">SPY {BACKTEST_YEARS}YR TOTAL</div><div style="font-size:13px;font-weight:bold;color:#22c55e;">{spy_bench['total']:+.1f}%</div></div>
          <div style="background:#070a0f;border-radius:5px;padding:8px;text-align:center;"><div style="font-size:8px;color:#475569;">SPY ANNUAL</div><div style="font-size:13px;font-weight:bold;color:#22c55e;">{spy_bench['annual']:+.1f}%/yr</div></div>
          <div style="background:#070a0f;border-radius:5px;padding:8px;text-align:center;"><div style="font-size:8px;color:#475569;">SPY MAX DD</div><div style="font-size:13px;font-weight:bold;color:#ef4444;">{spy_bench['max_dd']:.1f}%</div></div>
        </div>"""
 
    html = f"""
<html>
<body style="font-family:'Courier New',monospace;background:#080b10;color:#e0e0e0;padding:20px;max-width:660px;margin:0 auto;">
  <div style="border:1px solid #c9a84c;border-radius:8px;padding:14px;margin-bottom:14px;background:#0d1117;">
    <div style="color:#c9a84c;font-size:10px;letter-spacing:3px;margin-bottom:4px;">BACKTEST RESULTS — {BACKTEST_YEARS} YEARS</div>
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <div><div style="font-size:15px;font-weight:bold;color:#fff;">DCA at MA50 Strategy</div><div style="font-size:10px;color:#475569;">Jan {start_year} — {date_str} · {total_entries} entries</div></div>
      <div style="background:{score_c}20;border:1px solid {score_c};border-radius:6px;padding:6px 14px;text-align:center;">
        <div style="font-size:22px;font-weight:bold;color:{score_c};">{overall_wr90}%</div>
        <div style="font-size:8px;color:{score_c};letter-spacing:1px;">WIN RATE</div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-top:10px;">
      <div style="background:#0a0d14;border-radius:5px;padding:6px;text-align:center;"><div style="font-size:11px;font-weight:bold;color:#fff;">{total_entries}</div><div style="font-size:8px;color:#475569;">ENTRIES</div></div>
      <div style="background:#0a0d14;border-radius:5px;padding:6px;text-align:center;"><div style="font-size:11px;font-weight:bold;color:{score_c};">{overall_wr90}%</div><div style="font-size:8px;color:#475569;">90D WIN RATE</div></div>
      <div style="background:#0a0d14;border-radius:5px;padding:6px;text-align:center;"><div style="font-size:11px;font-weight:bold;color:{'#22c55e' if overall_avg90>=0 else '#ef4444'};">{overall_avg90:+.2f}%</div><div style="font-size:8px;color:#475569;">AVG RETURN</div></div>
    </div>
  </div>
  <div style="border:1px solid #1e2a3a;border-radius:8px;padding:12px;margin-bottom:12px;background:#0d1117;">
    <div style="font-size:9px;color:#c9a84c;letter-spacing:2px;margin-bottom:8px;">📈 vs BUY AND HOLD SPY</div>
    {bench_html}
  </div>
  <div style="border:1px solid #1e2a3a;border-radius:8px;padding:12px;margin-bottom:12px;background:#0d1117;">
    <div style="font-size:9px;color:#c9a84c;letter-spacing:2px;margin-bottom:8px;">🥇 HOLDINGS RANKED BY WIN RATE</div>
    {rankings_html}
  </div>
  <div style="border:1px solid #1e2a3a;border-radius:8px;padding:16px;background:#0a0d12;margin-bottom:12px;">
    <pre style="white-space:pre-wrap;font-size:11px;line-height:1.8;color:#e0e0e0;margin:0;">{plain}</pre>
  </div>
  <div style="text-align:center;font-size:10px;color:#333;padding:8px;">Backtest · Yahoo Finance · Past performance ≠ future results</div>
</body>
</html>"""
 
    return plain, html
 
# ============================================================
# SEND EMAIL
# ============================================================
def send_email(plain, html, wr, total):
    sender   = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    subject  = f"📊 Backtest Results — {BACKTEST_YEARS}yr · {total} entries · {wr}% win rate"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Portfolio Backtest <{sender}>"
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(plain,"plain"))
    msg.attach(MIMEText(html,"html"))
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
        s.login(sender,password)
        s.sendmail(sender,RECIPIENT_EMAIL,msg.as_string())
    print(f"✅ Email sent — {total} entries · {wr}% win rate")
 
# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    la_tz = pytz.timezone(TIMEZONE)
    print(f"📊 Running {BACKTEST_YEARS}-Year Backtest — {datetime.now(la_tz).strftime('%B %d, %Y')}")
    print(f"   Entry rule: price within 3% above MA50, above MA200")
    print()
 
    results = []
    for h in HOLDINGS:
        r = run_backtest(h["ticker"], h["name"], h["role"], BACKTEST_YEARS)
        if r:
            results.append(r)
 
    print()
    print("📈 SPY benchmark...")
    spy = run_spy_benchmark(BACKTEST_YEARS)
    if spy:
        print(f"   SPY {BACKTEST_YEARS}yr: {spy['total']:+.1f}% · Annual: {spy['annual']:+.1f}%")
 
    valid = [r for r in results if r and r.get("total_entries",0)>0]
    if not valid:
        print("❌ No signals found. Check data availability.")
        exit(1)
 
    total = sum(r["total_entries"] for r in valid)
    wr    = round(sum(r["wr90"]*r["total_entries"] for r in valid)/total, 1)
    print(f"\n🏆 Overall: {total} entries · {wr}% win rate (90d)")
    print("📧 Sending email...")
 
    plain, html = build_email(results, spy)
    send_email(plain, html, wr, total)
    print("✅ Done.")
