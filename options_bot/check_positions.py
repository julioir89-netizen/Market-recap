import requests
import os

SANDBOX_URL = "https://api.cert.tastyworks.com"
USERNAME    = "julioir89@gmail.com"
PASSWORD    = "Mompirri89!!"
ACCOUNT     = "5WK83147"

r = requests.post(
    f"{SANDBOX_URL}/sessions",
    json={"login": USERNAME, "password": PASSWORD},
    headers={"Content-Type": "application/json"}
)
token = r.json()["data"]["session-token"]
headers = {"Authorization": token}

positions = requests.get(
    f"{SANDBOX_URL}/accounts/{ACCOUNT}/positions",
    headers=headers
).json()

print("=== POSITIONS ===")
for p in positions.get("data", {}).get("items", []):
    print(f"{p.get('symbol')} | Qty: {p.get('quantity')} | Direction: {p.get('quantity-direction')}")

orders = requests.get(
    f"{SANDBOX_URL}/accounts/{ACCOUNT}/orders",
    headers=headers
).json()

print("\n=== RECENT ORDERS ===")
for o in orders.get("data", {}).get("items", [])[:5]:
    print(f"ID: {o.get('id')} | Status: {o.get('status')} | {o.get('underlying-symbol')}")
