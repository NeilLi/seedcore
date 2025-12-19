from dotenv import load_dotenv
import os
import time
import hmac
import hashlib
import requests
import json

load_dotenv()

ACCESS_ID = os.getenv("ACCESS_ID")
ACCESS_SECRET = os.getenv("ACCESS_SECRET")

# Singapore project: keep this if token works for you
BASE_URL = "https://openapi-sg.iotbing.com"

DEVICE_ID = "a35bbad286000d4c6blke1"


def ts_ms() -> str:
    return str(int(time.time() * 1000))


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def string_to_sign(method: str, path_with_query: str, body: str) -> str:
    # Tuya format: METHOD \n body_sha256 \n \n path
    return f"{method}\n{sha256_hex(body)}\n\n{path_with_query}"


def hmac_sha256_upper(key: str, msg: str) -> str:
    return (
        hmac.new(key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256)
        .hexdigest()
        .upper()
    )


def get_token() -> str:
    path = "/v1.0/token?grant_type=1"
    t = ts_ms()
    body = ""  # GET body empty

    sts = string_to_sign("GET", path, body)
    sign = hmac_sha256_upper(ACCESS_SECRET, ACCESS_ID + t + sts)

    headers = {
        "client_id": ACCESS_ID,
        "t": t,
        "sign_method": "HMAC-SHA256",
        "sign": sign,
    }

    r = requests.get(BASE_URL + path, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(data)

    return data["result"]["access_token"]

def control_switch(access_token: str, on: bool):
    """
    Turn the device switch ON or OFF
    Maps to:
    POST /v2.0/cloud/thing/{device_id}/shadow/actions
    """

    path = f"/v2.0/cloud/thing/{DEVICE_ID}/shadow/actions"

    payload = {
        "code": "switch",
        "input_params": {
            "value": on
        }
    }

    body = json.dumps(payload, separators=(",", ":"))
    t = ts_ms()

    sts = string_to_sign("POST", path, body)
    sign = hmac_sha256_upper(
        ACCESS_SECRET,
        ACCESS_ID + access_token + t + sts
    )

    headers = {
        "client_id": ACCESS_ID,
        "access_token": access_token,
        "t": t,
        "sign_method": "HMAC-SHA256",
        "sign": sign,
        "Content-Type": "application/json",
    }

    url = BASE_URL + path
    print(f"\n=== Sending SWITCH={'ON' if on else 'OFF'} ===")
    print("POST", url)
    print("Payload:", body)

    r = requests.post(url, headers=headers, data=body, timeout=15)

    print("Status:", r.status_code)
    print("Response:", r.text)

    return r.json()

def get_device_state(access_token: str):
    """
    Get current device state (all reported DPs)
    Maps to:
    GET /v2.0/cloud/thing/{device_id}/state
    """

    path = f"/v2.0/cloud/thing/{DEVICE_ID}/state"
    body = ""
    t = ts_ms()

    sts = string_to_sign("GET", path, body)
    sign = hmac_sha256_upper(
        ACCESS_SECRET,
        ACCESS_ID + access_token + t + sts
    )

    headers = {
        "client_id": ACCESS_ID,
        "access_token": access_token,
        "t": t,
        "sign_method": "HMAC-SHA256",
        "sign": sign,
    }

    url = BASE_URL + path
    print("\n=== Fetching Device State ===")
    print("GET", url)

    r = requests.get(url, headers=headers, timeout=15)

    print("Status:", r.status_code)
    print("Response:", r.text)

    if r.status_code == 200:
        data = r.json()
        if data.get("success"):
            return data["result"]

    return None





if __name__ == "__main__":
    if not ACCESS_ID or not ACCESS_SECRET:
        raise SystemExit("Missing ACCESS_ID / ACCESS_SECRET")

    # ------------------------------------------------------------
    # 1. Authenticate
    # ------------------------------------------------------------
    token = get_token()
    print("✅ Access token acquired")
    

    # Turn ON
    print("\nTurn on switch")
    control_switch(token, True)

    

    # Turn OFF
    print("\nTurn on switch")
    control_switch(token, False)

    state = get_device_state(token)
    print("Current State:", state)



