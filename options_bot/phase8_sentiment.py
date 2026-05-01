import os
import json
import requests
import yfinance as yf
from datetime import datetime, date, timedelta
 
# CONFIG
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID  = os.environ["TELEGRAM_CHAT_ID"]
 
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
 
WATCHLIST = ["SPY","QQQ","SOXX","AAPL","NVDA","MU","XLI","XLV","IAU","KBWB"]
 
 
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
 
 
# ─── MARKET DATA COLLECTOR ────────────────────────────────────────────────────
def collect_market_snapshot():
    """Collect current market data to feed into Claude."""
    try:
        spy  = yf.Ticker("SPY")
        qqq  = yf.Ticker("QQQ")
        vix  = yf.Ticker("^VIX")
        tlt  = yf.Ticker("TLT")
        gold = yf.Ticker("GLD")
 
        spy_hist = spy.history(period="10d")
        qqq_hist = qqq.history(period="5d")
        vix_hist = vix.history(period="10d")
        tlt_hist = tlt.history(period="5d")
        gld_hist = gold.history(period="5d")
 
        spy_close   = spy_hist["Close"]
        spy_price   = round(float(spy_close.iloc[-1]), 2)
        spy_prev    = round(float(spy_close.iloc[-2]), 2)
        spy_5d_ago  = round(float(spy_close.iloc[-5]), 2)
        spy_chg_1d  = round(((spy_price - spy_prev) / spy_prev) * 100, 2)
        spy_chg_5d  = round(((spy_price - spy_5d_ago) / spy_5d_ago) * 100, 2)
 
        spy_ma20   = round(float(spy_close.rolling(20).mean().iloc[-1]), 2)
        spy_above_20 = spy_price > spy_ma20
 
        vix_price  = round(float(vix_hist["Close"].iloc[-1]), 2)
        vix_prev   = round(float(vix_hist["Close"].iloc[-2]), 2)
        vix_5d_ago = round(float(vix_hist["Close"].iloc[-5]), 2)
        vix_chg_1d = round(vix_price - vix_prev, 2)
        vix_chg_5d = round(vix_price - vix_5d_ago, 2)
        vix_dir    = "RISING" if vix_chg_1d > 0 else "FALLING"
 
        qqq_price  = round(float(qqq_hist["Close"].iloc[-1]), 2)
        qqq_prev   = round(float(qqq_hist["Close"].iloc[-2]), 2)
        qqq_chg    = round(((qqq_price - qqq_prev) / qqq_prev) * 100, 2)
 
        tlt_price  = round(float(tlt_hist["Close"].iloc[-1]), 2)
        tlt_prev   = round(float(tlt_hist["Close"].iloc[-2]), 2)
        tlt_chg    = round(((tlt_price - tlt_prev) / tlt_prev) * 100, 2)
 
        gld_price  = round(float(gld_hist["Close"].iloc[-1]), 2)
        gld_prev   = round(float(gld_hist["Close"].iloc[-2]), 2)
        gld_chg    = round(((gld_price - gld_prev) / gld_prev) * 100, 2)
 
        # Sector strength
        sectors = {}
        for ticker, name in [("XLI","Industrials"),("XLV","Healthcare"),
                              ("XLK","Technology"),("XLF","Financials")]:
            try:
                t    = yf.Ticker(ticker)
                hist = t.history(period="5d")
                if not hist.empty:
                    p    = float(hist["Close"].iloc[-1])
                    prev = float(hist["Close"].iloc[-2])
                    sectors[name] = round(((p - prev) / prev) * 100, 2)
            except:
                pass
 
        return {
            "date":           date.today().isoformat(),
            "spy_price":      spy_price,
            "spy_chg_1d":     spy_chg_1d,
            "spy_chg_5d":     spy_chg_5d,
            "spy_above_ma20": spy_above_20,
            "spy_ma20":       spy_ma20,
            "vix_price":      vix_price,
            "vix_chg_1d":     vix_chg_1d,
            "vix_chg_5d":     vix_chg_5d,
            "vix_direction":  vix_dir,
            "qqq_price":      qqq_price,
            "qqq_chg_1d":     qqq_chg,
            "tlt_price":      tlt_price,
            "tlt_chg_1d":     tlt_chg,
            "gold_price":     gld_price,
            "gold_chg_1d":    gld_chg,
            "sectors":        sectors,
            "vix_regime":     (
                "FEAR" if vix_price > 28 else
                "ELEVATED" if vix_price > 22 else
                "NORMAL" if vix_price > 16 else
                "CALM"
            ),
        }
 
    except Exception as e:
        print(f"Market snapshot error: {e}")
        return {}
 
 
def collect_fed_context():
    """Build Fed context from known schedule."""
    fed_dates = [
        date(2026,1,29), date(2026,3,19), date(2026,4,29),
        date(2026,6,11), date(2026,7,29), date(2026,9,17),
        date(2026,11,5), date(2026,12,10),
    ]
    today      = date.today()
    days_ahead = [(d - today).days for d in fed_dates if (d - today).days >= 0]
    days_past  = [(today - d).days for d in fed_dates if (today - d).days >= 0]
 
    nearest_future = min(days_ahead) if days_ahead else 99
    nearest_past   = min(days_past)  if days_past  else 99
 
    return {
        "days_to_next_fed":   nearest_future,
        "days_since_last_fed": nearest_past,
        "fed_imminent":        nearest_future <= 3,
        "fed_this_week":       nearest_future <= 7,
        "post_fed_window":     nearest_past <= 3,
    }
 
 
def collect_watchlist_snapshot():
    """Get 1-day performance for all watchlist tickers."""
    perf = {}
    for ticker in WATCHLIST:
        try:
            t    = yf.Ticker(ticker)
            hist = t.history(period="3d")
            if not hist.empty and len(hist) >= 2:
                price = float(hist["Close"].iloc[-1])
                prev  = float(hist["Close"].iloc[-2])
                chg   = round(((price - prev) / prev) * 100, 2)
                perf[ticker] = {"price": round(price, 2), "chg_pct": chg}
        except:
            pass
    return perf
 
 
# ─── CLAUDE API CALL ─────────────────────────────────────────────────────────
def call_claude_sentiment(market_data, fed_context, watchlist_perf, regime, vix):
    """Call Claude API for market sentiment analysis."""
 
    # Build the structured prompt
    sector_lines = "\n".join([
        f"  {name}: {chg:+.2f}%"
        for name, chg in market_data.get("sectors", {}).items()
    ])
 
    watchlist_lines = "\n".join([
        f"  {ticker}: ${data['price']} ({data['chg_pct']:+.2f}%)"
        for ticker, data in watchlist_perf.items()
    ])
 
    prompt = f"""You are a senior options trading analyst providing a morning market briefing for a discretionary portfolio manager.
 
Today's date: {market_data.get('date', date.today().isoformat())}
 
MARKET DATA:
- SPY: ${market_data.get('spy_price')} ({market_data.get('spy_chg_1d', 0):+.2f}% today, {market_data.get('spy_chg_5d', 0):+.2f}% this week)
- SPY vs 20-day MA: {"ABOVE" if market_data.get('spy_above_ma20') else "BELOW"} (MA20: ${market_data.get('spy_ma20')})
- QQQ: ${market_data.get('qqq_price')} ({market_data.get('qqq_chg_1d', 0):+.2f}%)
- VIX: {market_data.get('vix_price')} ({market_data.get('vix_chg_1d', 0):+.2f} today, {market_data.get('vix_chg_5d', 0):+.2f} this week) - {market_data.get('vix_direction')} - {market_data.get('vix_regime')}
- TLT (Bonds): ${market_data.get('tlt_price')} ({market_data.get('tlt_chg_1d', 0):+.2f}%)
- Gold: ${market_data.get('gold_price')} ({market_data.get('gold_chg_1d', 0):+.2f}%)
 
CURRENT REGIME: {regime}
 
SECTOR PERFORMANCE:
{sector_lines}
 
WATCHLIST PERFORMANCE:
{watchlist_lines}
 
FED CONTEXT:
- Days to next Fed meeting: {fed_context.get('days_to_next_fed')}
- Days since last Fed meeting: {fed_context.get('days_since_last_fed')}
- Fed imminent (within 3 days): {fed_context.get('fed_imminent')}
 
UPCOMING EARNINGS ON WATCHLIST:
- NVDA: earnings in ~19 days (May 20, 2026)
- MU: earnings in ~54 days (June 24, 2026)
 
Based on this data, provide a concise market sentiment analysis in this EXACT format:
 
OVERALL_SENTIMENT: [BULLISH / NEUTRAL-BULLISH / NEUTRAL / NEUTRAL-BEARISH / BEARISH]
CONFIDENCE: [HIGH / MEDIUM / LOW]
VIX_ASSESSMENT: [one sentence about volatility environment]
REGIME_ASSESSMENT: [one sentence about whether current regime is likely to hold or shift]
KEY_RISK: [the single biggest risk to current positions today]
OPPORTUNITY: [the single best opportunity given current conditions]
EARNINGS_NOTE: [one sentence about NVDA earnings positioning]
STRATEGY_BIAS: [SELL PREMIUM / NEUTRAL / BUY PREMIUM]
SIZE_RECOMMENDATION: [FULL SIZE / REDUCED SIZE / MINIMAL / CASH]
MORNING_BRIEF: [2-3 sentences maximum - plain language summary for a trader opening their session]
 
Be direct and specific. No hedging. No disclaimers. Speak like a senior desk analyst."""
 
    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            },
            timeout=30
        )
 
        if response.status_code == 200:
            data    = response.json()
            content = data.get("content", [])
            for block in content:
                if block.get("type") == "text":
                    return block["text"]
            return None
        else:
            print(f"Claude API error: {response.status_code} - {response.text[:200]}")
            return None
 
    except Exception as e:
        print(f"Claude API exception: {e}")
        return None
 
 
# ─── PARSE CLAUDE RESPONSE ────────────────────────────────────────────────────
def parse_sentiment(raw_text):
    """Parse Claude's structured response into a dict."""
    result = {}
    if not raw_text:
        return result
 
    for line in raw_text.strip().split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
 
    return result
 
 
def sentiment_to_emoji(sentiment):
    mapping = {
        "BULLISH":          "🟢",
        "NEUTRAL-BULLISH":  "🟡",
        "NEUTRAL":          "⚪",
        "NEUTRAL-BEARISH":  "🟠",
        "BEARISH":          "🔴",
    }
    return mapping.get(sentiment, "⚪")
 
 
def size_to_action(size_rec):
    mapping = {
        "FULL SIZE":    "Deploy full framework positions",
        "REDUCED SIZE": "Trade at 50-75% normal size",
        "MINIMAL":      "Very small positions only",
        "CASH":         "Stay mostly cash today",
    }
    return mapping.get(size_rec, size_rec)
 
 
# ─── BUILD TELEGRAM MESSAGE ───────────────────────────────────────────────────
def build_sentiment_telegram(parsed, market_data, regime, vix):
    sentiment   = parsed.get("OVERALL_SENTIMENT", "NEUTRAL")
    confidence  = parsed.get("CONFIDENCE", "MEDIUM")
    emoji       = sentiment_to_emoji(sentiment)
    size_rec    = parsed.get("SIZE_RECOMMENDATION", "REDUCED SIZE")
    size_action = size_to_action(size_rec)
 
    return (
        f"<b>AI MARKET SENTIMENT - {datetime.now().strftime('%b %d %Y')}</b>\n\n"
        f"{emoji} <b>{sentiment}</b>  |  Confidence: {confidence}\n"
        f"Regime: {regime}  |  VIX: {vix}\n\n"
        f"<b>Morning Brief:</b>\n"
        f"{parsed.get('MORNING_BRIEF', 'No brief available.')}\n\n"
        f"<b>VIX:</b> {parsed.get('VIX_ASSESSMENT', 'N/A')}\n\n"
        f"<b>Regime:</b> {parsed.get('REGIME_ASSESSMENT', 'N/A')}\n\n"
        f"<b>Key Risk:</b> {parsed.get('KEY_RISK', 'N/A')}\n\n"
        f"<b>Opportunity:</b> {parsed.get('OPPORTUNITY', 'N/A')}\n\n"
        f"<b>NVDA Earnings:</b> {parsed.get('EARNINGS_NOTE', 'N/A')}\n\n"
        f"<b>Strategy Bias:</b> {parsed.get('STRATEGY_BIAS', 'N/A')}\n"
        f"<b>Size Today:</b> {size_rec} — {size_action}"
    )
 
 
# ─── BUILD EMAIL SECTION ──────────────────────────────────────────────────────
def build_sentiment_email_section(parsed, market_data):
    sentiment  = parsed.get("OVERALL_SENTIMENT", "NEUTRAL")
    confidence = parsed.get("CONFIDENCE", "MEDIUM")
    size_rec   = parsed.get("SIZE_RECOMMENDATION", "REDUCED SIZE")
 
    return f"""
AI SENTIMENT ANALYSIS (Claude)
{"=" * 40}
Overall Sentiment:  {sentiment}
Confidence:         {confidence}
Strategy Bias:      {parsed.get('STRATEGY_BIAS', 'N/A')}
Size Today:         {size_rec}
 
Morning Brief:
{parsed.get('MORNING_BRIEF', 'N/A')}
 
VIX Assessment:
{parsed.get('VIX_ASSESSMENT', 'N/A')}
 
Regime Assessment:
{parsed.get('REGIME_ASSESSMENT', 'N/A')}
 
Key Risk Today:
{parsed.get('KEY_RISK', 'N/A')}
 
Best Opportunity:
{parsed.get('OPPORTUNITY', 'N/A')}
 
NVDA Earnings Note:
{parsed.get('EARNINGS_NOTE', 'N/A')}
{"=" * 40}
"""
 
 
# ─── MAIN ─────────────────────────────────────────────────────────────────────
def run_sentiment_analysis(regime="C", vix=20.0):
    """
    Main entry point. Called from combined_run.py with regime and vix.
    Returns parsed sentiment dict and formatted email section.
    """
    print("=== PHASE 8: CLAUDE SENTIMENT ===")
 
    print("  Collecting market data...")
    market_data     = collect_market_snapshot()
    fed_context     = collect_fed_context()
    watchlist_perf  = collect_watchlist_snapshot()
 
    print("  Calling Claude API...")
    raw_sentiment = call_claude_sentiment(
        market_data, fed_context, watchlist_perf, regime, vix
    )
 
    if not raw_sentiment:
        print("  Claude API returned no response.")
        return None, None
 
    print("  Parsing sentiment response...")
    parsed = parse_sentiment(raw_sentiment)
 
    print(f"  Sentiment: {parsed.get('OVERALL_SENTIMENT', 'N/A')}")
    print(f"  Size rec:  {parsed.get('SIZE_RECOMMENDATION', 'N/A')}")
 
    # Send to Telegram
    tg_msg = build_sentiment_telegram(parsed, market_data, regime, vix)
    telegram_send(tg_msg)
 
    # Build email section
    email_section = build_sentiment_email_section(parsed, market_data)
 
    return parsed, email_section
 
 
def main():
    """Standalone run for testing."""
    print("=== PHASE 8: CLAUDE AI SENTIMENT LAYER ===")
    print(f"Date: {date.today()}")
 
    parsed, email_section = run_sentiment_analysis(regime="A", vix=17.5)
 
    if parsed:
        print("\nSentiment Output:")
        for k, v in parsed.items():
            print(f"  {k}: {v}")
        print("\nEmail section preview:")
        print(email_section)
    else:
        print("No sentiment generated.")
 
    print("Done.")
 
 
if __name__ == "__main__":
    main()
