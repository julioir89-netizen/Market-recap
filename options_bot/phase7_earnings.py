import os
import csv
import math
import requests
import yfinance as yf
import smtplib
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
 
# CONFIG
EMAIL_TO         = os.environ["EMAIL_TO"]
EMAIL_FROM       = os.environ["EMAIL_FROM"]
EMAIL_PASS       = os.environ["EMAIL_PASSWORD"]
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
 
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
 
WATCHLIST = ["SPY","QQQ","SOXX","AAPL","NVDA","MU","XLI","XLV","IAU","KBWB"]
 
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_log.csv")
 
 
# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
def telegram_send(text):
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print(f"Telegram error: {e}")
 
 
# ─── TRADE LOG ────────────────────────────────────────────────────────────────
def load_trade_log():
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        return list(csv.DictReader(f))
 
 
def get_open_trades():
    return [t for t in load_trade_log() if t.get("status", "") == "OPEN"]
 
 
# ─── EARNINGS DETECTION ───────────────────────────────────────────────────────
def get_earnings_date(ticker):
    """
    Pull next earnings date using multiple fallback methods.
    Returns date object or None.
    """
    # ETFs never have earnings - skip immediately
    etfs = ["SPY","QQQ","XLI","XLV","IAU","SOXX","GLD","SLV","TLT","IWM"]
    if ticker in etfs:
        return None
 
    try:
        t = yf.Ticker(ticker)
 
        # Method 1 - earnings_dates (most reliable in newer yfinance)
        try:
            ed = t.earnings_dates
            if ed is not None and not ed.empty:
                today = date.today()
                future_dates = []
                for idx in ed.index:
                    try:
                        d = idx.date() if hasattr(idx, "date") else idx
                        if d >= today:
                            future_dates.append(d)
                    except:
                        continue
                if future_dates:
                    return min(future_dates)
        except Exception as e:
            print(f"    Method 1 failed for {ticker}: {e}")
 
        # Method 2 - calendar attribute
        try:
            cal = t.calendar
            if cal is not None:
                # Newer yfinance returns dict
                if isinstance(cal, dict):
                    for key in ["Earnings Date", "earningsDate"]:
                        if key in cal and cal[key]:
                            val = cal[key]
                            if isinstance(val, list):
                                dates = []
                                for d in val:
                                    try:
                                        d2 = d.date() if hasattr(d, "date") else d
                                        if d2 >= date.today():
                                            dates.append(d2)
                                    except:
                                        pass
                                if dates:
                                    return min(dates)
                # Older yfinance returns DataFrame
                elif hasattr(cal, "empty") and not cal.empty:
                    if "Earnings Date" in cal.index:
                        raw = cal.loc["Earnings Date"]
                        if hasattr(raw, "__iter__"):
                            dates = []
                            for d in raw:
                                if d is not None:
                                    try:
                                        d2 = d.date() if hasattr(d, "date") else d
                                        if d2 >= date.today():
                                            dates.append(d2)
                                    except:
                                        pass
                            if dates:
                                return min(dates)
        except Exception as e:
            print(f"    Method 2 failed for {ticker}: {e}")
 
        # Method 3 - info dict
        try:
            info = t.info
            if info:
                for key in ["earningsDate", "earningsTimestamp", "nextEarningsDate"]:
                    if key in info and info[key]:
                        val = info[key]
                        if isinstance(val, (int, float)):
                            d = date.fromtimestamp(val)
                        elif isinstance(val, list) and val:
                            d = date.fromtimestamp(val[0])
                        else:
                            continue
                        if d >= date.today():
                            return d
        except Exception as e:
            print(f"    Method 3 failed for {ticker}: {e}")
 
        print(f"    No earnings date found for {ticker} via any method")
        return None
 
    except Exception as e:
        print(f"  Earnings date error for {ticker}: {e}")
        return None
 
 
def get_known_earnings():
    """
    Hardcoded upcoming earnings for watchlist tickers.
    Update this quarterly. Format: ticker -> date string YYYY-MM-DD
    These are Q1 2026 / Q2 2026 estimates based on historical patterns.
    """
    return {
        "AAPL": "2026-08-06",
        "NVDA": "2026-05-28",
        "MU":   "2026-06-25",
        "KBWB": None,
    }
 
 
def get_earnings_date_with_fallback(ticker):
    """Try Yahoo Finance first, then use hardcoded fallback."""
    yahoo_date = get_earnings_date(ticker)
    if yahoo_date:
        return yahoo_date
 
    known = get_known_earnings()
    if ticker in known and known[ticker]:
        try:
            return datetime.strptime(known[ticker], "%Y-%m-%d").date()
        except:
            pass
    return None
    """
    Calculate implied move using ATM straddle price.
    Formula: (ATM Call + ATM Put) / Stock Price
    """
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if hist.empty:
            return None, None
 
        stock_price = float(hist["Close"].iloc[-1])
        chain       = t.option_chain(expiration_str)
        calls       = chain.calls
        puts        = chain.puts
 
        # Find ATM strike (closest to current price)
        all_strikes = sorted(set(list(calls["strike"].values)))
        atm_strike  = min(all_strikes, key=lambda x: abs(x - stock_price))
 
        call_row = calls[calls["strike"] == atm_strike]
        put_row  = puts[puts["strike"] == atm_strike]
 
        if call_row.empty or put_row.empty:
            return None, stock_price
 
        call_price = float(call_row.iloc[0].get("lastPrice", 0))
        put_price  = float(put_row.iloc[0].get("lastPrice", 0))
 
        if call_price == 0 and put_price == 0:
            return None, stock_price
 
        implied_move_pct = round(((call_price + put_price) / stock_price) * 100, 2)
        implied_move_dollar = round(call_price + put_price, 2)
 
        return {
            "pct":          implied_move_pct,
            "dollar":       implied_move_dollar,
            "stock_price":  round(stock_price, 2),
            "atm_strike":   atm_strike,
            "call_price":   call_price,
            "put_price":    put_price,
            "expiration":   expiration_str,
        }, stock_price
 
    except Exception as e:
        print(f"  Implied move error for {ticker}: {e}")
        return None, None
 
 
def get_implied_move(ticker, expiration_str):
    """
    Calculate implied move using ATM straddle price.
    Formula: (ATM Call + ATM Put) / Stock Price
    """
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if hist.empty:
            return None, None
 
        stock_price = float(hist["Close"].iloc[-1])
        chain       = t.option_chain(expiration_str)
        calls       = chain.calls
        puts        = chain.puts
 
        all_strikes = sorted(set(list(calls["strike"].values)))
        atm_strike  = min(all_strikes, key=lambda x: abs(x - stock_price))
 
        call_row = calls[calls["strike"] == atm_strike]
        put_row  = puts[puts["strike"] == atm_strike]
 
        if call_row.empty or put_row.empty:
            return None, stock_price
 
        call_price = float(call_row.iloc[0].get("lastPrice", 0))
        put_price  = float(put_row.iloc[0].get("lastPrice", 0))
 
        if call_price == 0 and put_price == 0:
            return None, stock_price
 
        implied_move_pct    = round(((call_price + put_price) / stock_price) * 100, 2)
        implied_move_dollar = round(call_price + put_price, 2)
 
        return {
            "pct":         implied_move_pct,
            "dollar":      implied_move_dollar,
            "stock_price": round(stock_price, 2),
            "atm_strike":  atm_strike,
            "call_price":  call_price,
            "put_price":   put_price,
            "expiration":  expiration_str,
        }, stock_price
 
    except Exception as e:
        print(f"  Implied move error for {ticker}: {e}")
        return None, None
 
 
def get_nearest_expiration(ticker, target_dte=7):
    """Get the expiration closest to earnings date."""
    try:
        t           = yf.Ticker(ticker)
        expirations = t.options
        if not expirations:
            return None
        today    = date.today()
        best_exp = None
        best_diff = 999
        for exp_str in expirations:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte      = (exp_date - today).days
            diff     = abs(dte - target_dte)
            if diff < best_diff:
                best_diff = diff
                best_exp  = exp_str
        return best_exp
    except:
        return None
 
 
# ─── EARNINGS IMPACT ANALYZER ─────────────────────────────────────────────────
def analyze_earnings_impact(ticker, earnings_date, open_trades):
    """
    Determine if an upcoming earnings event impacts open positions.
    """
    today     = date.today()
    days_away = (earnings_date - today).days
    impacts   = []
 
    for trade in open_trades:
        if trade["ticker"] != ticker:
            continue
        exp_date = datetime.strptime(trade["expiration"], "%Y-%m-%d").date()
        dte_left = (exp_date - today).days
 
        # Earnings falls within the DTE window
        if days_away <= dte_left:
            impacts.append({
                "trade":      trade,
                "days_away":  days_away,
                "dte_left":   dte_left,
                "risk_level": "HIGH" if days_away <= 2 else "MEDIUM" if days_away <= 7 else "LOW"
            })
 
    return impacts
 
 
def grade_earnings_setup(ticker, days_to_earnings, implied_move, iv_rank):
    """
    Score an earnings-related options strategy.
    Returns recommended approach and grade.
    """
    score = 0
 
    # Days timing
    if 1 <= days_to_earnings <= 2:
        approach = "IV CRUSH SELL"
        score   += 30
    elif 3 <= days_to_earnings <= 5:
        approach = "PRE-EARNINGS SELL"
        score   += 20
    elif 6 <= days_to_earnings <= 14:
        approach = "DIRECTIONAL POST-EARNINGS"
        score   += 15
    else:
        approach = "WAIT"
        score   += 5
 
    # IV environment
    if iv_rank is not None:
        if iv_rank > 70:
            score += 30
        elif iv_rank > 50:
            score += 20
        elif iv_rank > 30:
            score += 10
 
    # Implied move size (bigger move = more opportunity)
    if implied_move and implied_move.get("pct"):
        pct = implied_move["pct"]
        if pct > 10:
            score += 25
        elif pct > 7:
            score += 20
        elif pct > 5:
            score += 15
        elif pct > 3:
            score += 10
 
    if score >= 70:
        grade = "A"
    elif score >= 55:
        grade = "B+"
    elif score >= 40:
        grade = "B"
    else:
        grade = "SKIP"
 
    return approach, grade, score
 
 
def get_iv_rank(ticker):
    """Get IVR using 52-week range proxy."""
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period="1y")
        if hist.empty:
            return None
        hist["range"] = hist["High"] - hist["Low"]
        current_range = float(hist["range"].iloc[-1])
        high_52w      = float(hist["range"].max())
        low_52w       = float(hist["range"].min())
        if high_52w == low_52w:
            return 50
        return round(((current_range - low_52w) / (high_52w - low_52w)) * 100, 1)
    except:
        return None
 
 
# ─── MAIN SCAN ────────────────────────────────────────────────────────────────
def run_earnings_scan():
    today       = date.today()
    open_trades = get_open_trades()
    results     = []
    warnings    = []
 
    print(f"Scanning earnings for {len(WATCHLIST)} tickers...")
 
    for ticker in WATCHLIST:
        print(f"  Checking {ticker}...")
 
        earnings_date = get_earnings_date_with_fallback(ticker)
        if not earnings_date:
            print(f"    No earnings date found for {ticker}")
            continue
 
        days_away = (earnings_date - today).days
 
        if days_away < 0:
            print(f"    {ticker} earnings was {abs(days_away)} days ago")
            continue
 
        print(f"    {ticker} earnings in {days_away} days ({earnings_date})")
 
        # Only process earnings within 30 days
        if days_away > 30:
            print(f"    {ticker} earnings too far away ({days_away} days)")
            continue
 
        # Get IV rank
        iv_rank = get_iv_rank(ticker)
 
        # Get nearest weekly expiration for implied move
        exp_for_iv = get_nearest_expiration(ticker, target_dte=days_away + 1)
        implied_move_data = None
        if exp_for_iv:
            implied_move_data, stock_price = get_implied_move(ticker, exp_for_iv)
        else:
            try:
                hist = yf.Ticker(ticker).history(period="2d")
                stock_price = float(hist["Close"].iloc[-1]) if not hist.empty else None
            except:
                stock_price = None
 
        # Check if earnings impacts any open positions
        impacts = analyze_earnings_impact(ticker, earnings_date, open_trades)
        for impact in impacts:
            trade = impact["trade"]
            warnings.append({
                "ticker":       ticker,
                "earnings":     earnings_date,
                "days_away":    days_away,
                "trade":        trade,
                "risk_level":   impact["risk_level"],
            })
 
        # Grade the earnings opportunity
        approach, grade, score = grade_earnings_setup(
            ticker, days_away, implied_move_data, iv_rank
        )
 
        if grade != "SKIP":
            results.append({
                "ticker":         ticker,
                "earnings_date":  earnings_date,
                "days_away":      days_away,
                "approach":       approach,
                "grade":          grade,
                "score":          score,
                "implied_move":   implied_move_data,
                "iv_rank":        iv_rank,
                "stock_price":    stock_price,
            })
 
    return results, warnings
 
 
# ─── BUILD TELEGRAM MESSAGE ───────────────────────────────────────────────────
def build_earnings_telegram(results, warnings):
    today_str = datetime.now().strftime("%b %d %Y - %I:%M %p PT")
 
    # Open position warnings first
    if warnings:
        warn_lines = []
        for w in warnings:
            t = w["trade"]
            warn_lines.append(
                f"{w['ticker']} earnings in {w['days_away']} days "
                f"({w['earnings_date']}) — {w['risk_level']} RISK\n"
                f"  Open trade: {t['strikes']} exp {t['expiration']}\n"
                f"  Earnings falls within your DTE window"
            )
 
        telegram_send(
            f"<b>EARNINGS WARNING - OPEN POSITIONS AT RISK</b>\n"
            f"{today_str}\n\n" +
            "\n\n".join(warn_lines) +
            f"\n\nReview these positions before earnings.\n"
            f"Framework: reduce size or close before event."
        )
 
    # Earnings opportunities
    if results:
        for r in results[:5]:
            iv_str  = f"{r['iv_rank']}" if r["iv_rank"] else "N/A"
            sp_str  = f"${r['stock_price']}" if r["stock_price"] else "N/A"
 
            if r["implied_move"]:
                im = r["implied_move"]
                im_str = (
                    f"Implied Move: +/-{im['pct']}% (${im['dollar']})\n"
                    f"ATM Strike: {im['atm_strike']}\n"
                    f"Call: ${im['call_price']}  Put: ${im['put_price']}"
                )
            else:
                im_str = "Implied Move: N/A"
 
            strategy_detail = ""
            if r["approach"] == "IV CRUSH SELL":
                strategy_detail = (
                    f"Strategy: Sell credit spread INTO earnings\n"
                    f"Close SAME DAY as earnings release\n"
                    f"IV crush will collapse premium after report\n"
                    f"Use 50% normal size — DEFINED RISK only"
                )
            elif r["approach"] == "PRE-EARNINGS SELL":
                strategy_detail = (
                    f"Strategy: Sell credit spread 3-5 days before\n"
                    f"Close before earnings release\n"
                    f"Capture IV expansion then exit\n"
                    f"Do NOT hold through the event"
                )
            elif r["approach"] == "DIRECTIONAL POST-EARNINGS":
                strategy_detail = (
                    f"Strategy: Wait for earnings release\n"
                    f"Enter debit spread AFTER IV normalizes\n"
                    f"Post-earnings entry is cleaner and safer\n"
                    f"IV will be reset — Greeks will be accurate"
                )
 
            telegram_send(
                f"<b>EARNINGS SETUP - {r['ticker']}</b>\n"
                f"Grade: {r['grade']} ({r['score']}/100)\n"
                f"Earnings: {r['earnings_date']} ({r['days_away']} days away)\n"
                f"Stock: {sp_str}  IVR: {iv_str}\n\n"
                f"{im_str}\n\n"
                f"{strategy_detail}\n\n"
                f"Approach: {r['approach']}"
            )
    else:
        telegram_send(
            f"<b>EARNINGS SCANNER</b>\n"
            f"{today_str}\n\n"
            f"No earnings setups within 30 days.\n"
            f"All clear on watchlist."
        )
 
 
# ─── BUILD EMAIL ─────────────────────────────────────────────────────────────
def build_earnings_email(results, warnings):
    today_str = datetime.now().strftime("%A, %B %d %Y - %I:%M %p PT")
 
    warning_section = ""
    if warnings:
        warning_section = "OPEN POSITION EARNINGS WARNINGS\n"
        warning_section += "=" * 40 + "\n"
        for w in warnings:
            t = w["trade"]
            warning_section += (
                f"{w['ticker']} - Earnings in {w['days_away']} days ({w['earnings_date']})\n"
                f"  Risk Level:   {w['risk_level']}\n"
                f"  Open Trade:   {t['strategy']}\n"
                f"  Strikes:      {t['strikes']}\n"
                f"  Expiration:   {t['expiration']}\n"
                f"  Action:       Review and consider reducing before earnings\n\n"
            )
 
    results_section = ""
    if results:
        results_section = "EARNINGS OPPORTUNITIES\n"
        results_section += "=" * 40 + "\n"
        for r in results:
            iv_str = f"{r['iv_rank']}" if r["iv_rank"] else "N/A"
            sp_str = f"${r['stock_price']}" if r["stock_price"] else "N/A"
 
            if r["implied_move"]:
                im     = r["implied_move"]
                im_str = f"+/-{im['pct']}% (${im['dollar']})"
            else:
                im_str = "N/A"
 
            results_section += (
                f"{r['ticker']} - Grade {r['grade']} ({r['score']}/100)\n"
                f"  Earnings:      {r['earnings_date']} ({r['days_away']} days away)\n"
                f"  Stock:         {sp_str}\n"
                f"  IVR:           {iv_str}\n"
                f"  Implied Move:  {im_str}\n"
                f"  Approach:      {r['approach']}\n\n"
            )
    else:
        results_section = "No earnings setups found within 30 days.\n"
 
    body = f"""OPTIONS BOT - EARNINGS SCANNER REPORT
{today_str}
 
{warning_section}
{results_section}
EARNINGS FRAMEWORK RULES
1. Never buy long premium going INTO earnings
2. If selling INTO earnings: defined risk only, 50% size
3. Close credit spreads SAME DAY as earnings release
4. Best entry is AFTER earnings when IV resets
5. Check implied move vs actual move for edge tracking
6. Implied move = (ATM Call + ATM Put) / Stock Price
 
Options Bot v1.0 | Phase 7 - Earnings Scanner Active
"""
 
    msg = MIMEMultipart()
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg["Subject"] = (
        f"OPTIONS BOT | Earnings Scanner | "
        f"{len(results)} Setups | {len(warnings)} Warnings | "
        f"{date.today().strftime('%b %d')}"
    )
    msg.attach(MIMEText(body, "plain"))
 
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASS)
        server.send_message(msg)
    print("Earnings email sent.")
 
 
# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print("=== PHASE 7: EARNINGS SCANNER ===")
    print(f"Date: {date.today()}")
 
    results, warnings = run_earnings_scan()
 
    print(f"\nResults:  {len(results)} earnings setups found")
    print(f"Warnings: {len(warnings)} open positions at risk")
 
    for r in results:
        print(f"  {r['ticker']}: {r['approach']} | Grade {r['grade']} | Earnings {r['earnings_date']}")
 
    for w in warnings:
        print(f"  WARNING: {w['ticker']} earnings in {w['days_away']} days | {w['risk_level']} risk")
 
    build_earnings_telegram(results, warnings)
    build_earnings_email(results, warnings)
 
    print("Done.")
 
 
if __name__ == "__main__":
    main()
