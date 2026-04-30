import requests
import os

LIVE_URL     = "https://api.tastyworks.com"
TT_LIVE_USER = os.environ["TT_LIVE_USERNAME"]
TT_LIVE_PASS = os.environ["TT_LIVE_PASSWORD"]

r = requests.post(
    f"{LIVE_URL}/sessions",
    json={
        "login":       TT_LIVE_USER,
        "password":    TT_LIVE_PASS,
        "remember-me": True
    },
    headers={"Content-Type": "application/json"}
)

print(f"Status: {r.status_code}")
print(f"Response: {r.text}")
