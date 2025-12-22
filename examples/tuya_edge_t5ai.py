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

def send_dp_action(access_token: str, code: str, value):
    """
    Send a DP action to the device
    POST /v2.0/cloud/thing/{device_id}/shadow/actions
    """
    path = f"/v2.0/cloud/thing/{DEVICE_ID}/shadow/actions"

    payload = {
        "code": code,
        "input_params": {
            "value": value
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
    print(f"\n=== Sending DP {code} = {value} ===")

    r = requests.post(url, headers=headers, data=body, timeout=15)
    print("Status:", r.status_code)
    print("Response:", r.text)

    r.raise_for_status()
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


def verify_switch(access_token: str):
    """🔘 Verify switch/relay simulator (DP 1)"""
    print("\n🔘 Verifying SWITCH simulator")

    send_dp_action(access_token, "switch", True)
    time.sleep(1)

    send_dp_action(access_token, "switch", False)
    time.sleep(1)


def verify_light(access_token: str):
    """💡 Verify light simulator (DP 5, 6, 7)"""
    print("\n💡 Verifying LIGHT simulator")

    # Turn light on
    send_dp_action(access_token, "light_on", True)
    time.sleep(1)

    # Set brightness
    send_dp_action(access_token, "brightness", 80)
    time.sleep(1)

    # Set RGB color
    send_dp_action(access_token, "rgb_color", "255,64,0")
    time.sleep(1)

    # Turn light off
    send_dp_action(access_token, "light_on", False)
    time.sleep(1)


def verify_camera(access_token: str):
    """📷 Verify camera simulator (DP 2, 3, 4)"""
    print("\n📷 Verifying CAMERA simulator")

    # Motion detected
    send_dp_action(access_token, "motion_detected", True)
    time.sleep(1)
    send_dp_action(access_token, "motion_detected", False)
    time.sleep(1)

    # Person detected
    send_dp_action(access_token, "person_detected", True)
    time.sleep(1)
    send_dp_action(access_token, "person_detected", False)
    time.sleep(1)

    # Anomaly score
    send_dp_action(access_token, "anomaly_score", 72)
    time.sleep(1)



if __name__ == "__main__":
    if not ACCESS_ID or not ACCESS_SECRET:
        raise SystemExit("Missing ACCESS_ID / ACCESS_SECRET")

    # ------------------------------------------------------------
    # 1. Authenticate
    # ------------------------------------------------------------
    token = get_token()
    print("✅ Access token acquired")

    # ------------------------------------------------------------
    # 2. Verify simulators
    # ------------------------------------------------------------
    verify_switch(token)
    verify_light(token)
    verify_camera(token)

    # ------------------------------------------------------------
    # 3. Read back device state
    # ------------------------------------------------------------
    state = get_device_state(token)
    print("\n📊 Final Device State:")
    print(json.dumps(state, indent=2))



