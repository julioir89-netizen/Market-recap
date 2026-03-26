import anthropic
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import pytz

# ============================================================
# YOUR PORTFOLIO — DO NOT EDIT UNLESS YOUR HOLDINGS CHANGE
# ============================================================
HOLDINGS = [
    {"ticker": "SPY",  "name": "S&P 500 ETF",                  "avg_cost": 673.15,   "shares": 0.22775013},
    {"ticker": "QQQ",  "name": "Invesco QQQ",                  "avg_cost": 597.57,   "shares": 0.14075326},
    {"ticker": "SOXX", "name": "iShares Semiconductor ETF",    "avg_cost": 330.78,   "shares": 0.18441232},
    {"ticker": "AAPL", "name": "Apple",                        "avg_cost": 257.30,   "shares": 0.35021052},
    {"ticker": "NVDA", "name": "Nvidia",                       "avg_cost": 181.46,   "shares": 0.55107155},
    {"ticker": "MU",   "name": "Micron Technology",            "avg_cost": 376.93,   "shares": 0.16183304},
    {"ticker": "XLI",  "name": "Industrial Select Sector SPDR","avg_cost": 169.10,   "shares": 0.34299159},
    {"ticker": "XLV",  "name": "Healthcare Select Sector SPDR","avg_cost": 156.27,   "shares": 0.25475002},
    {"ticker": "IAU",  "name": "iShares Gold Trust",           "avg_cost": 93.76,    "shares": 0.30930709},
    {"ticker": "KBWB", "name": "KBW Bank ETF",                 "avg_cost": 80.14,    "shares": 0.56149156},
    {"ticker": "BTC",  "name": "Bitcoin",                      "avg_cost": 71896.01, "shares": 0.00084780},
]

RECIPIENT_EMAIL = "julioir89@gmail.com"
TIMEZONE = "America/Los_Angeles"

# ============================================================
# DETERMINE WHICH RECAP TO RUN BASED ON CURRENT TIME
# ============================================================
def get_recap_type():
    """Auto-detect which recap to run based on Pacific Time."""
    forced = os.environ.get("RECAP_TYPE")
    if forced:
        return forced

    la_tz = pytz.timezone(TIMEZONE)
    now = datetime.now(la_tz)
    hour, minute = now.hour, now.minute

    if hour == 5:
        return "morning"
    elif hour == 7 and minute >= 25:
        return "midday"
    elif hour == 16:
        return "close"
    else:
        # Default fallback
        return "morning"

# ============================================================
# RECAP PROMPTS — FULL STRUCTURED FORMAT
# ============================================================
def build_prompt(recap_type):
    la_tz = pytz.timezone(TIMEZONE)
    now = datetime.now(la_tz)
    date_str = now.strftime("%A, %B %d, %Y")

    holdings_text = "\n".join([
        f"  - {h['ticker']} ({h['name']}): avg cost ${h['avg_cost']:,.2f} | {h['shares']} shares"
        for h in HOLDINGS
    ])

    base_context = f"""You are a professional portfolio analyst delivering a market recap to a retail investor.

TODAY'S DATE: {date_str} (Pacific Time)

INVESTOR'S PORTFOLIO (11 holdings):
{holdings_text}

IMPORTANT NOTES:
- Most positions are currently below average cost — flag DCA opportunities based on actual entry prices
- Research EVERY holding individually using web search
- Be specific, data-driven, and actionable
- Use Pacific Time for all event times
- Format cleanly for email reading on mobile"""

    if recap_type == "morning":
        return base_context + """

TASK: Generate a complete PRE-MARKET MORNING RECAP.
Search for: overnight futures, international markets, breaking news, macro data, anything moving these holdings.

OUTPUT FORMAT — follow this structure exactly:

🌅 MORNING MARKET BRIEFING — PRE-MARKET STRATEGY
📅 {date}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(0) 🚨 BREAKING NEWS RADAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
List 4-6 breaking stories. For each:
- Headline | Source | Time
- Which holdings are affected and how (bullish/bearish/neutral)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(1) 🌍 OVERNIGHT MACRO DRIVERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 🛢 Oil: [price + direction + implication]
- 📉 Treasury Yields: [2Y and 10Y + tech implication]
- 💵 USD: [direction + global liquidity impact]
- 🪙 Gold: [price + fear/confidence read]
- ₿ Bitcoin: [price + risk appetite signal]
→ OVERALL BIAS BEFORE OPEN: [Bullish / Neutral / Bearish]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(2) ⚖️ SENTIMENT SCORE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bullish headlines: [N]
Bearish headlines: [N]
Weighted Score: [+X / -X / Neutral]
→ Translation: [one sentence plain English]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(3) 📅 ECONOMIC CALENDAR (PACIFIC TIME)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TODAY:
- [Time PT] — [Event] — [Importance: HIGH/MED/LOW]
REST OF WEEK:
- [Key events]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(4) 🔄 SECTOR ROTATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 Leading: [sectors]
🔴 Lagging: [sectors]
🟡 Mixed: [sectors]
→ Interpretation: [rotation type — bull/bear/defensive]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(5) 📊 HOLDINGS GAME PLAN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For EACH of the 11 holdings:

[TICKER] — [Current Price] | Avg Cost: $X | [+/-% from avg]
  S1: $X (-X% away)
  S2: $X (-X% away)
  DCA Readiness: ✅ Near support / ❌ Not yet / ⚠️ Wait
  → [1-line action note]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(6) 🧾 OPTIONS FLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Put/Call ratio: [X]
- Institutional positioning: [hedging / neutral / aggressive]
→ Smart money read: [one line]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(7) 🎯 RISK DIAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[ DEFENSIVE ] / [ NEUTRAL ] / [ AGGRESSIVE ]
Reasons for: [2-3 bullet points]
Reasons against going more aggressive: [1-2 bullets]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(8) 🧠 INTELLIGENT INVESTOR SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[3-4 sentences in plain English. What's really happening and why it matters to this portfolio.]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ TODAY'S ACTION PLAN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. First 30-60 min: [instruction]
2. Only buy if: [specific condition + ticker]
3. Avoid: [specific tickers + reason]
4. Key trigger to watch: [specific level or event]"""

    elif recap_type == "midday":
        return base_context + """

TASK: Generate a MIDDAY MARKET UPDATE.
Search for: what has moved since open, breaking news since 6:30 AM PT, current prices, intraday action.

OUTPUT FORMAT — follow this structure exactly:

⏱️ MIDDAY MARKET UPDATE — REAL-TIME ADJUSTMENT
📅 {date}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(0) 🚨 BREAKING NEWS SINCE OPEN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
New headlines that changed the picture since 6:30 AM PT

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(1) 📊 WHAT MOVED MARKETS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Oil: [change since open]
- Yields: [direction since open]
- Dollar, Gold, Bitcoin: [moves]
→ Real driver of price action today: [plain English]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(2) ⚖️ UPDATED SENTIMENT SCORE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
vs Morning: [improving / worsening / same]
Current score: [+X / -X]
→ [One line — is market stronger or weaker than expected?]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(3) 🔄 INTRADAY ROTATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Growth vs Defensive — who's winning?
→ Real move or fake move? [reasoning]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(4) 📊 HOLDINGS CHECK — LIVE EXECUTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For EACH holding:
[TICKER]: $[current] | [+/-% today] | Distance to S1: X% | Action: BUY / WAIT / AVOID

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(5) 🎯 RISK DIAL UPDATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[ DEFENSIVE ] / [ NEUTRAL ] / [ AGGRESSIVE ]
Change from morning? [Yes/No + reason]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(6) ⚠️ IMMEDIATE CATALYSTS AHEAD TODAY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Any Fed speakers, auctions, or surprises still coming today

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(7) 🧾 OPTIONS FLOW — INTRADAY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
→ Smart money buying or hedging right now?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ MIDDAY DECISION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
→ [BUY / WAIT / AVOID] — specific tickers and triggers
→ One key thing to watch into the close"""

    else:  # close
        return base_context + """

TASK: Generate the AFTER-MARKET CLOSE RECAP.
Search for: today's closing prices, full day performance, what drove the day, after-hours news, tomorrow's calendar.

OUTPUT FORMAT — follow this structure exactly:

🌇 AFTER-MARKET RECAP — STRATEGIC REVIEW
📅 {date}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(0) 🚨 FULL-DAY NEWS SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
What actually mattered today — top 4-5 stories and their market impact

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(1) 📊 WHAT MOVED MARKETS — CAUSE & EFFECT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Event] → [Market reaction] → [Portfolio implication]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(2) ⚖️ FINAL SENTIMENT SCORE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Today's overall tone: [Bullish / Neutral / Bearish]
Score: [+X / -X]
→ [One line summary of the day]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(3) 🔄 SECTOR ROTATION — CONFIRMED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Who led, who lagged
→ Where is capital moving next?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(4) 📊 HOLDINGS — CLOSING REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For EACH holding:
[TICKER]: Close $X | Avg Cost $X | [+/-% from avg] | [+/-% today]
  Support levels: S1 $X | S2 $X
  DCA Readiness: ✅/❌/⚠️
  → [Updated positioning note]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(5) 🎯 RISK DIAL — END OF DAY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tomorrow's posture: [ DEFENSIVE ] / [ NEUTRAL ] / [ AGGRESSIVE ]
Reasoning: [2-3 bullets]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(6) 🧠 KEY INDICATORS CHECKLIST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- SPY behavior today: [summary]
- Growth vs Defensives: [who won]
- SOXX strength: [read]
- VIX: [level + fear/complacency signal]
- Bitcoin: [risk appetite read]
→ Market health: [HEALTHY / CAUTIOUS / STRESSED]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(7) 🧾 OPTIONS FLOW RECAP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
→ How did institutional positioning close?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(8) 📅 TOMORROW'S CALENDAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Key events tomorrow (Pacific Time):
- [Time] — [Event] — [Impact level]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ TOMORROW'S GAME PLAN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. What changed today that affects tomorrow
2. Key levels to watch at open
3. Best DCA setups if market dips
4. What would change the risk dial"""


# ============================================================
# CALL CLAUDE API WITH WEB SEARCH
# ============================================================
def run_recap(recap_type):
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    prompt = build_prompt(recap_type)

    print(f"🔍 Running {recap_type.upper()} recap with live web research...")

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}]
    )

    # Extract all text blocks from response
    recap_text = ""
    for block in response.content:
        if hasattr(block, "type") and block.type == "text":
            recap_text += block.text

    return recap_text


# ============================================================
# SEND EMAIL VIA GMAIL
# ============================================================
def send_email(recap_text, recap_type):
    sender = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")

    subjects = {
        "morning": "🌅 Morning Market Briefing — Pre-Market Strategy",
        "midday":  "⏱️ Midday Market Update — Real-Time Adjustment",
        "close":   "🌇 After-Market Recap — Strategic Review",
    }

    subject = subjects.get(recap_type, "📊 Market Recap")

    html_body = f"""
<html>
<body style="font-family: 'Courier New', monospace; background-color: #080b10;
             color: #e0e0e0; padding: 24px; max-width: 680px; margin: 0 auto;">
  <div style="border: 1px solid #c9a84c; border-radius: 8px; padding: 20px;">
    <pre style="white-space: pre-wrap; font-size: 13px; line-height: 1.7;
                color: #e0e0e0; margin: 0;">{recap_text}</pre>
  </div>
  <p style="color: #555; font-size: 11px; text-align: center; margin-top: 16px;">
    Automated Market Recap System — Powered by Claude AI
  </p>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Market Recap <{sender}>"
    msg["To"] = RECIPIENT_EMAIL

    msg.attach(MIMEText(recap_text, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, RECIPIENT_EMAIL, msg.as_string())

    print(f"✅ {recap_type.upper()} recap sent to {RECIPIENT_EMAIL}")


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    recap_type = get_recap_type()
    print(f"📊 Recap type: {recap_type.upper()}")

    recap_content = run_recap(recap_type)
    send_email(recap_content, recap_type)
