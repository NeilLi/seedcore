import time
import hmac
import hashlib
import requests
import json

# =========================
# CONFIG — FILL THESE
# =========================
ACCESS_ID = os.getenv("ACCESS_ID", "YOUR_ACCESS_ID")
ACCESS_SECRET = os.getenv("ACCESS_SECRET", "YOUR_ACCESS_SECRET")

DEVICE_ID = "vdevo176597070597050"
REGION = "https://openapi.tuyaus.com"  # Singapore

# =========================
# TUYA SIGNATURE HELPERS
# =========================
def get_timestamp():
    return str(int(time.time() * 1000))

def sign(method, url, body, timestamp):
    message = ACCESS_ID + timestamp + method + "\n"
    message += hashlib.sha256(body.encode("utf-8")).hexdigest()
    message += "\n\n" + url

    return hmac.new(
        ACCESS_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest().upper()

def get_headers(method, url, body=""):
    timestamp = get_timestamp()
    signature = sign(method, url, body, timestamp)

    return {
        "client_id": ACCESS_ID,
        "sign": signature,
        "t": timestamp,
        "sign_method": "HMAC-SHA256",
        "Content-Type": "application/json"
    }

# =========================
# PUSH AI SIGNAL
# =========================
def push_ai_signal():
    path = f"/v1.0/devices/{DEVICE_ID}/commands"
    url = REGION + path

    payload = {
        "commands": [
            {"code": "event_type", "value": "human"},
            {"code": "anomaly_score", "value": 87},
            {"code": "policy_action", "value": "warn"},
            {
                "code": "explanation",
                "value": "Unrecognized human detected near entry zone"
            }
        ]
    }

    body = json.dumps(payload)
    headers = get_headers("POST", path, body)

    response = requests.post(url, headers=headers, data=body)
    print("Status:", response.status_code)
    print("Response:", response.text)

# =========================
# RUN
# =========================
if __name__ == "__main__":
    push_ai_signal()

