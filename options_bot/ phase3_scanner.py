import os
import csv
import json
import requests
import yfinance as yf
import smtplib
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ─── CONFIG ───────────────────────────────────────────────────────────────────
SANDBOX_URL  = "https://api.cert.tastyworks.com"
TT_USERNAME  = os.environ["TT_SANDBOX_USERNAME"]
TT_PASSWORD  = os.environ["TT_SANDBOX_PASSWORD"]
TT_ACCOUNT   = os.environ["TT_SANDBOX_ACCOUNT"]
EMAIL_TO     = os.environ["EMAIL_TO"]
EMAIL_FROM   = os.environ["EMAIL_FROM"]
EMAIL_PASS   = os.environ["EMAIL_PASSWORD"]

WATCHLIST = ["SPY", "QQQ", "SOXX", "AAPL", "NVDA", "MU", "XLI", "XLV", "IAU", "KBWB"]

LOG_FILE = "options_bot/trade_log.csv"
LOG_HEADERS = [
    "date", "ticker", "strategy", "strikes", "expiration", "dte",
    "delta", "gamma", "theta", "ivr", "grade", "score",
    "max_risk", "max_gain", "regime", "status", "pl_result", "notes"
]

# ─── TASTYTRADE AUTH ──────────────────────────────────────────────────────────
def get_session_token():
    r = requests.post(
        f"{SANDBOX_URL}/sessions",
        json={"login": TT_USERNAME, "password": TT_PASSWORD},
        headers={"Content-Type": "application/json"}
    )
    r.raise_for_status()
    return r.json()["data"]["session-token"]

def tt_headers(token):
    return {
        "Authorization": token,
        "Content-Type": "application/json"
    }

# ─── OPTIONS CHAIN FETCH ─────────────────────────────────────────────────────
def get_option_chain(token, ticker):
    try:
        r = requests.get(
            f"{SANDBOX_URL}/option-chains/{ticker}/nested",
            headers=tt_headers(token)
        )
        if r.status_code != 200:
            return None
        return r.json().get("data", {}).get("items", [])
    except Exception as e:
        print(f"  Chain error {ticker}: {e}")
        return None

def get_market_metrics(token, tickers):
    try:
        symbols = ",".join(tickers)
        r = requests.get(
            f"{SANDBOX_URL}/market-metrics?symbols={symbols}",
            headers=tt_headers(token)
        )
        if r.status_code != 200:
            return {}
        items = r.json().get("data", {}).get("items", [])
        return {item["symbol"]: item for item in items}
    except Exception as e:
        print(f"  Metrics error: {e}")
        return {}

# ─── IVR FROM TASTYTRADE ─────────────────────────────────────────────────────
def extract_ivr(metrics, ticker):
    try:
        m = metrics.get(ticker, {})
        iv_rank = m.get("iv-rank")
        iv_pct  = m.get("iv-percentile")
        if iv_rank is not None:
            ivr = round(float(iv_rank) * 100, 1)
        elif iv_pct is not None:
            ivr = round(float(iv_pct) * 100, 1)
        else:
            return None, "No IVR data"

        if ivr < 25:
            bias = "BUY (debit spreads)"
        elif ivr < 50:
            bias = "BUY-LEAN"
        elif ivr < 75:
            bias = "NEUTRAL"
        elif ivr < 90:
            bias = "SELL (credit spreads)"
        else:
            bias = "EXTREME — far OTM only"

        return ivr, bias
    except:
        return None, "Error"

# ─── FIND BEST STRIKES ───────────────────────────────────────────────────────
def find_best_expiration(chain, min_dte=30, max_dte=60):
    today = date.today()
    best  = None
    best_dte = 999

    for expiry_group in chain:
        exp_str = expiry_group.get("expiration-date", "")
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if min_dte <= dte <= max_dte:
                if dte < best_dte:
                    best_dte = dte
                    best = expiry_group
        except:
            continue

    return best, best_dte

def find_strike_by_delta(strikes, target_delta_min, target_delta_max, option_type="C"):
    candidates = []
    for strike in strikes:
        for opt in strike.get("options", []):
            if opt.get("option-type") != option_type:
                continue
            greeks = opt.get("greeks", {})
            delta  = greeks.get("delta")
            if delta is None:
                continue
            delta = abs(float(delta))
            if target_delta_min <= delta <= target_delta_max:
                candidates.append({
                    "strike":       float(strike.get("strike-price", 0)),
                    "delta":        round(delta, 3),
                    "gamma":        round(abs(float(greeks.get("gamma", 0))), 4),
                    "theta":        round(float(greeks.get("theta", 0)), 4),
                    "vega":         round(float(greeks.get("vega", 0)), 4),
                    "iv":           round(float(greeks.get("volatility", 0)) * 100, 1),
                    "option_type":  option_type,
                })
    if not candidates:
        return None
    # Return the one closest to middle of target range
    target_mid = (target_delta_min + target_delta_max) / 2
    return min(candidates, key=lambda x: abs(x["delta"] - target_mid))

# ─── GREEK FILTER ────────────────────────────────────────────────────────────
def greek_filter(delta, gamma, theta, dte, strategy_type):
    flags  = []
    passed = True

    if strategy_type == "debit":
        if not (0.40 <= delta <= 0.65):
            flags.append(f"Delta {delta} outside 0.40-0.65")
            passed = False
        if gamma > 0.06:
            flags.append(f"Gamma {gamma} above 0.06")
            passed = False
        if theta < -0.09:
            flags.append(f"Theta {theta} worse than -0.09")
            passed = False
        if not (30 <= dte <= 90):
            flags.append(f"DTE {dte} outside 30-90")
            passed = False

    elif strategy_type == "credit":
        if not (0.15 <= delta <= 0.30):
            flags.append(f"Delta {delta} outside 0.15-0.30")
            passed = False
        if gamma > 0.05:
            flags.append(f"Gamma {gamma} above 0.05")
            passed = False
        if theta < 0.05:
            flags.append(f"Theta {theta} below +0.05")
            passed = False
        if not (25 <= dte <= 50):
            flags.append(f"DTE {dte} outside 25-50")
            passed = False

    return passed, flags

# ─── TRADE SCORER ────────────────────────────────────────────────────────────
def score_setup(regime, ivr, delta, gamma, theta, dte,
                strategy_type, vix, event_color):
    score = 0

    # Regime match (25 pts)
    regime_strategy_match = {
        "A": ["debit", "credit"],
        "B": ["debit", "credit"],
        "C": ["credit", "condor"],
        "D": ["credit"],
        "E": [],
    }
    if strategy_type in regime_strategy_match.get(regime, []):
        score += 25
    else:
        score += 5

    # IVR alignment (20 pts)
    if ivr is not None:
        if strategy_type == "debit" and ivr < 40:
            score += 20
        elif strategy_type == "debit" and ivr < 60:
            score += 12
        elif strategy_type == "credit" and ivr > 60:
            score += 20
        elif strategy_type == "credit" and ivr > 40:
            score += 12
        else:
            score += 5

    # Greek quality (25 pts)
    greek_score = 0
    if strategy_type == "debit":
        if 0.45 <= delta <= 0.60:
            greek_score += 10
        elif 0.40 <= delta <= 0.65:
            greek_score += 7
        if gamma <= 0.04:
            greek_score += 8
        elif gamma <= 0.06:
            greek_score += 5
        if theta >= -0.05:
            greek_score += 7
        elif theta >= -0.08:
            greek_score += 4
    else:
        if 0.18 <= delta <= 0.25:
            greek_score += 10
        elif 0.15 <= delta <= 0.30:
            greek_score += 7
        if gamma <= 0.03:
            greek_score += 8
        elif gamma <= 0.05:
            greek_score += 5
        if theta >= 0.08:
            greek_score += 7
        elif theta >= 0.05:
            greek_score += 4
    score += greek_score

    # DTE quality (15 pts)
    if strategy_type == "debit":
        if 45 <= dte <= 75:
            score += 15
        elif 35 <= dte <= 90:
            score += 10
        else:
            score += 3
    else:
        if 30 <= dte <= 45:
            score += 15
        elif 25 <= dte <= 50:
            score += 10
        else:
            score += 3

    # VIX environment (10 pts)
    if vix < 18:
        score += 10
    elif vix < 22:
        score += 7
    elif vix < 28:
        score += 4
    else:
        score += 0

    # Event risk (5 pts)
    if "GREEN" in event_color:
        score += 5
    elif "YELLOW" in event_color:
        score += 2

    return min(score, 100)

def score_to_grade(score):
    if score >= 90:
        return "A+", "STRONG RECOMMEND — full size", "🟢"
    elif score >= 80:
        return "A",  "RECOMMEND — full size", "🟢"
    elif score >= 70:
        return "A-", "RECOMMEND — reduced size OK", "🟢"
    elif score >= 60:
        return "B+", "BORDERLINE — your call", "🟡"
    elif score >= 50:
        return "B",  "GRAY ZONE — lean toward skip", "🟡"
    else:
        return "—",  "INSUFFICIENT EDGE", "🔴"

# ─── STRATEGY BUILDER ────────────────────────────────────────────────────────
def build_bull_call_spread(token, ticker, chain, dte, regime,
                            ivr, vix, event_color):
    exp_group, actual_dte = find_best_expiration(chain, 35, 75)
    if not exp_group:
        return None

    strikes = exp_group.get("strikes", [])
    long_leg  = find_strike_by_delta(strikes, 0.40, 0.65, "C")
    if not long_leg:
        return None
    short_leg = find_strike_by_delta(strikes, 0.20, 0.35, "C")
    if not short_leg:
        return None
    if short_leg["strike"] <= long_leg["strike"]:
        return None

    passed, flags = greek_filter(
        long_leg["delta"], long_leg["gamma"],
        long_leg["theta"], actual_dte, "debit"
    )

    spread_width = short_leg["strike"] - long_leg["strike"]
    max_risk     = round(spread_width * 40, 0)   # rough estimate, 1 contract
    max_gain     = round(spread_width * 60, 0)

    score = score_setup(regime, ivr, long_leg["delta"], long_leg["gamma"],
                        long_leg["theta"], actual_dte, "debit", vix, event_color)
    grade, desc, emoji = score_to_grade(score)

    if score < 50:
        return None

    return {
        "ticker":      ticker,
        "strategy":    "Bull Call Debit Spread",
        "type":        "debit",
        "direction":   "BULLISH",
        "long_strike":  long_leg["strike"],
        "short_strike": short_leg["strike"],
        "expiration":   exp_group.get("expiration-date"),
        "dte":          actual_dte,
        "delta":        long_leg["delta"],
        "gamma":        long_leg["gamma"],
        "theta":        long_leg["theta"],
        "iv":           long_leg["iv"],
        "max_risk":     max_risk,
        "max_gain":     max_gain,
        "score":        score,
        "grade":        grade,
        "grade_desc":   desc,
        "emoji":        emoji,
        "greek_passed": passed,
        "greek_flags":  flags,
        "live_ready":   max_risk <= 300,
    }

def build_put_credit_spread(token, ticker, chain, dte, regime,
                             ivr, vix, event_color):
    exp_group, actual_dte = find_best_expiration(chain, 25, 50)
    if not exp_group:
        return None

    strikes   = exp_group.get("strikes", [])
    short_leg = find_strike_by_delta(strikes, 0.15, 0.30, "P")
    if not short_leg:
        return None
    long_leg  = find_strike_by_delta(strikes, 0.05, 0.14, "P")
    if not long_leg:
        return None
    if long_leg["strike"] >= short_leg["strike"]:
        return None

    passed, flags = greek_filter(
        short_leg["delta"], short_leg["gamma"],
        short_leg["theta"], actual_dte, "credit"
    )

    spread_width = short_leg["strike"] - long_leg["strike"]
    max_risk     = round(spread_width * 70, 0)
    max_gain     = round(spread_width * 30, 0)

    score = score_setup(regime, ivr, short_leg["delta"], short_leg["gamma"],
                        short_leg["theta"], actual_dte, "credit", vix, event_color)
    grade, desc, emoji = score_to_grade(score)

    if score < 50:
        return None

    return {
        "ticker":       ticker,
        "strategy":     "Put Credit Spread",
        "type":         "credit",
        "direction":    "BULLISH-NEUTRAL",
        "long_strike":  long_leg["strike"],
        "short_strike": short_leg["strike"],
        "expiration":   exp_group.get("expiration-date"),
        "dte":          actual_dte,
        "delta":        short_leg["delta"],
        "gamma":        short_leg["gamma"],
        "theta":        short_leg["theta"],
        "iv":           short_leg["iv"],
        "max_risk":     max_risk,
        "max_gain":     max_gain,
        "score":        score,
        "grade":        grade,
        "grade_desc":   desc,
        "emoji":        emoji,
        "greek_passed": passed,
        "greek_flags":  flags,
        "live_ready":   max_risk <= 300,
    }

# ─── SCAN ALL TICKERS ─────────────────────────────────────────────────────────
def scan_all_tickers(token, regime, vix, event_color):
    print("Fetching market metrics...")
    metrics  = get_market_metrics(token, WATCHLIST)
    setups   = []

    for ticker in WATCHLIST:
        print(f"  Scanning {ticker}...")
        chain = get_option_chain(token, ticker)
        if not chain:
            print(f"    No chain data for {ticker}")
            continue

        ivr, ivr_bias = extract_ivr(metrics, ticker)

        # Regime A or B → try bull call spread
        if regime in ["A", "B"]:
            setup = build_bull_call_spread(
                token, ticker, chain, 45,
                regime, ivr, vix, event_color
            )
            if setup:
                setup["ivr"]      = ivr
                setup["ivr_bias"] = ivr_bias
                setups.append(setup)

        # All regimes → try put credit spread
        setup = build_put_credit_spread(
            token, ticker, chain, 35,
            regime, ivr, vix, event_color
        )
        if setup:
            setup["ivr"]      = ivr
            setup["ivr_bias"] = ivr_bias
            setups.append(setup)

    # Sort by score descending
    setups.sort(key=lambda x: x["score"], reverse=True)

    # Only return grade B+ and above
    return [s for s in setups if s["score"] >= 60]

# ─── P/L TRACKER ─────────────────────────────────────────────────────────────
def load_trade_log():
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        reader = csv.DictReader(f)
        return list(reader)

def save_trade_log(trades):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_HEADERS)
        writer.writeheader()
        writer.writerows(trades)

def log_new_setups(setups, regime):
    trades    = load_trade_log()
    today_str = date.today().isoformat()

    # Don't duplicate — check if same ticker+strategy already logged today
    existing = {(t["date"], t["ticker"], t["strategy"]) for t in trades}

    for s in setups:
        key = (today_str, s["ticker"], s["strategy"])
        if key not in existing:
            trades.append({
                "date":        today_str,
                "ticker":      s["ticker"],
                "strategy":    s["strategy"],
                "strikes":     f"{s['long_strike']}/{s['short_strike']}",
                "expiration":  s["expiration"],
                "dte":         s["dte"],
                "delta":       s["delta"],
                "gamma":       s["gamma"],
                "theta":       s["theta"],
                "ivr":         s.get("ivr", "N/A"),
                "grade":       s["grade"],
                "score":       s["score"],
                "max_risk":    s["max_risk"],
                "max_gain":    s["max_gain"],
                "regime":      regime,
                "status":      "OPEN",
                "pl_result":   "",
                "notes":       "",
            })
            existing.add(key)

    save_trade_log(trades)
    return trades

def get_performance_summary(trades):
    closed = [t for t in trades if t["status"] in ["WIN", "LOSS", "SCRATCH"]]
    if not closed:
        return None

    total  = len(closed)
    wins   = len([t for t in closed if t["status"] == "WIN"])
    losses = len([t for t in closed if t["status"] == "LOSS"])
    win_rate = round((wins / total) * 100, 1) if total > 0 else 0

    pl_values = []
    for t in closed:
        try:
            pl_values.append(float(t["pl_result"]))
        except:
            pass
    total_pl = round(sum(pl_values), 2)

    # Grade accuracy
    a_plus = [t for t in closed if t["grade"] == "A+"]
    a_plus_wins = len([t for t in a_plus if t["status"] == "WIN"])
    a_plus_rate = round((a_plus_wins / len(a_plus)) * 100, 1) if a_plus else 0

    return {
        "total":        total,
        "wins":         wins,
        "losses":       losses,
        "win_rate":     win_rate,
        "total_pl":     total_pl,
        "a_plus_count": len(a_plus),
        "a_plus_rate":  a_plus_rate,
        "open_trades":  len([t for t in trades if t["status"] == "OPEN"]),
    }

# ─── EMAIL BUILDER ────────────────────────────────────────────────────────────
def format_setup_block(i, s):
    greek_status = "✅ ALL GREEK FILTERS PASSED" if s["greek_passed"] \
                   else f"⚠️  FLAGS: {', '.join(s['greek_flags'])}"
    live_tag     = "✅ LIVE READY ($2k account)" if s["live_ready"] \
                   else "📋 Paper only (need larger account)"
    ivr_str      = f"{s['ivr']}" if s.get("ivr") else "N/A"

    return f"""
─────────────────────────────────────────
SETUP #{i} — {s['ticker']}  {s['emoji']} GRADE: {s['grade']} ({s['score']}/100)
─────────────────────────────────────────
Strategy:    {s['strategy']}
Direction:   {s['direction']}
Strikes:     {s['long_strike']} / {s['short_strike']}
Expiration:  {s['expiration']}  ({s['dte']} DTE)

GREEKS:
  Delta:     {s['delta']}
  Gamma:     {s['gamma']}
  Theta:     {s['theta']}
  IV:        {s['iv']}%

IVR:         {ivr_str}  → {s.get('ivr_bias', 'N/A')}

RISK/REWARD:
  Max Risk:  ${s['max_risk']} per contract
  Max Gain:  ${s['max_gain']} per contract

{greek_status}
{s['grade_desc']}
{live_tag}
"""

def build_full_email(regime, regime_label, vix, event_label,
                     setups, perf, today_str):
    header = f"""
╔══════════════════════════════════════════╗
   OPTIONS BOT — FULL DAILY REPORT
   {today_str}
╚══════════════════════════════════════════╝

REGIME {regime} — {regime_label}
VIX: {vix}  |  EVENT: {event_label}
"""

    if not setups:
        setup_section = """
━━━ TRADE SETUPS ━━━━━━━━━━━━━━━━━━━━━━━━
  No setups passed the framework filters today.
  Regime or Greek conditions not favorable.
  NO-GO — wait for better environment.
"""
    else:
        setup_section = f"\n━━━ TRADE SETUPS ({len(setups)} FOUND) ━━━━━━━━━━━━━━━━━\n"
        for i, s in enumerate(setups[:5], 1):   # max 5 setups per email
            setup_section += format_setup_block(i, s)

    if perf:
        pl_emoji = "🟢" if perf["total_pl"] >= 0 else "🔴"
        perf_section = f"""
━━━ P/L TRACKER (Paper Account) ━━━━━━━━
  Record:        {perf['wins']}W / {perf['losses']}L  ({perf['win_rate']}% win rate)
  Total P/L:     {pl_emoji} ${perf['total_pl']:+.2f}
  Open trades:   {perf['open_trades']}
  A+ accuracy:   {perf['a_plus_rate']}%  ({perf['a_plus_count']} trades)

  Target: 60%+ win rate before going live
"""
    else:
        perf_section = """
━━━ P/L TRACKER (Paper Account) ━━━━━━━━
  No closed trades yet — tracking starts today.
  Close trades in trade_log.csv to build record.
"""

    footer = """
━━━ FRAMEWORK REMINDER ━━━━━━━━━━━━━━━━━
  1. Regime first — always
  2. Greeks must pass filter before entry
  3. IVR guides buy vs sell bias
  4. Grade B+ minimum — skip anything below
  5. YOU confirm every trade before execution
  6. Paper trade until 20+ trades logged
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Options Bot v1.0 | Phase 3 — Scanner Active
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    return header + setup_section + perf_section + footer

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
    today_str  = datetime.now().strftime("%A, %B %d %Y — %I:%M %p PT")

    # Get regime from environment (set by Phase 1 if run together)
    # or re-run the quick regime check
    regime      = os.environ.get("REGIME", "A")
    regime_label = os.environ.get("REGIME_LABEL", "BULL TREND")
    vix_str     = os.environ.get("VIX_PRICE", "N/A")
    event_label = os.environ.get("EVENT_LABEL", "No event data")
    event_color = os.environ.get("EVENT_COLOR", "GREEN")

    try:
        vix = float(vix_str)
    except:
        vix = 20.0

    print("Authenticating with Tastytrade sandbox...")
    token = get_session_token()
    print("Authentication successful.")

    print("Scanning options chains...")
    setups = scan_all_tickers(token, regime, vix, event_color)
    print(f"Found {len(setups)} valid setups.")

    print("Logging setups to trade log...")
    all_trades = log_new_setups(setups, regime)
    perf       = get_performance_summary(all_trades)

    subject = (
        f"OPTIONS BOT | Regime {regime} | "
        f"{len(setups)} Setups | "
        f"VIX {vix_str} | "
        f"{date.today().strftime('%b %d')}"
    )

    body = build_full_email(
        regime, regime_label, vix_str,
        event_label, setups, perf, today_str
    )

    send_email(subject, body)
    print("Done.")

if __name__ == "__main__":
    main()
