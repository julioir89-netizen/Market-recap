import os
import sys

# Add the options_bot directory to Python path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from phase1_regime import (
    get_market_data, get_ivr, check_event_risk,
    classify_regime, calculate_grade
)
from phase3_scanner import (
    get_session_token, scan_all_tickers,
    log_new_setups, get_performance_summary,
    build_full_email, send_email
)
from datetime import datetime, date
from datetime import datetime, date

def main():
    today_str = datetime.now().strftime("%A, %B %d %Y — %I:%M %p PT")

    print("=== PHASE 1: REGIME ENGINE ===")
    data                         = get_market_data()
    ivr_spy, ivr_bias_spy        = get_ivr("SPY")
    event_label, event_status    = check_event_risk()
    event_color                  = event_status.split("—")[0].strip()
    regime, regime_label, strats = classify_regime(data, data["vix_price"])
    score, grade, grade_desc     = calculate_grade(
        regime, ivr_spy, data["vix_price"],
        event_color, data["spy_chg_pct"]
    )

    print(f"Regime: {regime} — {regime_label}")
    print(f"Grade:  {grade} ({score}/100)")
    print(f"VIX:    {data['vix_price']} ({data['vix_dir']})")
    print(f"Event:  {event_label}")

    print("\n=== PHASE 3: OPTIONS SCANNER ===")
    token  = get_session_token()
    setups = scan_all_tickers(
        token, regime, data["vix_price"], event_color
    )
    print(f"Valid setups found: {len(setups)}")

    all_trades = log_new_setups(setups, regime)
    perf       = get_performance_summary(all_trades)

    subject = (
        f"OPTIONS BOT | Regime {regime} {grade} | "
        f"{len(setups)} Setups | "
        f"VIX {data['vix_price']} | "
        f"{date.today().strftime('%b %d')}"
    )

    body = build_full_email(
        regime, regime_label,
        str(data["vix_price"]), event_label,
        setups, perf, today_str
    )

    send_email(subject, body)
    print("Complete — email sent.")

if __name__ == "__main__":
    main()
