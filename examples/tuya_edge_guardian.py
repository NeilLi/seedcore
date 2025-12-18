from dotenv import load_dotenv
import os
import time
import hmac
import hashlib
import requests
import json
from urllib.parse import urlencode, quote

load_dotenv()

ACCESS_ID = os.getenv("ACCESS_ID")
ACCESS_SECRET = os.getenv("ACCESS_SECRET")

# Singapore project: keep this if token works for you
BASE_URL = "https://openapi-sg.iotbing.com"

DEVICE_ID = "vdevo176597070597050"


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


def issue_properties(access_token: str):
    # Cloud Services API: Send Property
    path = f"/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties/issue"

    # Your DPs (must be PROPERTY type in the product data model)
    props = {
        "event_type": "human",
        "anomaly_score": 87,
        "policy_action": "warn",
        "explanation": "Unrecognized human detected near entry zone",
    }

    # NOTE: this endpoint expects "properties" as a JSON STRING (per docs)
    payload = {"properties": json.dumps(props, separators=(",", ":"))}
    body = json.dumps(payload, separators=(",", ":"))

    t = ts_ms()
    sts = string_to_sign("POST", path, body)
    sign = hmac_sha256_upper(ACCESS_SECRET, ACCESS_ID + access_token + t + sts)

    headers = {
        "client_id": ACCESS_ID,
        "access_token": access_token,
        "t": t,
        "sign_method": "HMAC-SHA256",
        "sign": sign,
        "Content-Type": "application/json",
    }

    r = requests.post(BASE_URL + path, headers=headers, data=body, timeout=15)
    print("POST", BASE_URL + path)
    print("Status:", r.status_code)
    print("Response:", r.text)


def get_state(access_token: str):
    path = f"/v2.0/cloud/thing/{DEVICE_ID}/state"
    body = ""
    t = ts_ms()

    sts = string_to_sign("GET", path, body)
    sign = hmac_sha256_upper(ACCESS_SECRET, ACCESS_ID + access_token + t + sts)

    headers = {
        "client_id": ACCESS_ID,
        "access_token": access_token,
        "t": t,
        "sign_method": "HMAC-SHA256",
        "sign": sign,
    }

    r = requests.get(BASE_URL + path, headers=headers, timeout=15)
    print("GET", BASE_URL + path)
    print("Status:", r.status_code)
    print("Response:", r.text)


def get_details(access_token: str):
    path = f"/v2.0/cloud/thing/{DEVICE_ID}"
    body = ""
    t = ts_ms()

    sts = string_to_sign("GET", path, body)
    sign = hmac_sha256_upper(ACCESS_SECRET, ACCESS_ID + access_token + t + sts)

    headers = {
        "client_id": ACCESS_ID,
        "access_token": access_token,
        "t": t,
        "sign_method": "HMAC-SHA256",
        "sign": sign,
    }

    r = requests.get(BASE_URL + path, headers=headers, timeout=15)
    print("GET", BASE_URL + path)
    print("Status:", r.status_code)
    print("Response:", r.text)


def get_device_model(access_token: str):
    """Get the device's data model to see available data point codes"""
    path = f"/v2.0/cloud/thing/{DEVICE_ID}/model"
    body = ""
    t = ts_ms()

    sts = string_to_sign("GET", path, body)
    sign = hmac_sha256_upper(ACCESS_SECRET, ACCESS_ID + access_token + t + sts)

    headers = {
        "client_id": ACCESS_ID,
        "access_token": access_token,
        "t": t,
        "sign_method": "HMAC-SHA256",
        "sign": sign,
    }

    r = requests.get(BASE_URL + path, headers=headers, timeout=15)
    print("GET", BASE_URL + path)
    print("Status:", r.status_code)
    print("Response:", r.text)
    
    if r.status_code == 200:
        data = r.json()
        if data.get("success") and "result" in data:
            result = data["result"]
            # The model is returned as a JSON string, need to parse it
            model_str = result.get("model", "{}")
            try:
                model_data = json.loads(model_str)
                print("\n=== Parsed Device Model ===")
                
                # Extract properties from services
                all_codes = []
                code_to_ability_id = {}
                if "services" in model_data:
                    for service in model_data.get("services", []):
                        properties = service.get("properties", [])
                        if properties:
                            print("\n=== Available Property Codes ===")
                            for prop in properties:
                                code = prop.get("code")
                                name = prop.get("name")
                                access_mode = prop.get("accessMode")
                                ability_id = prop.get("abilityId")
                                prop_type = prop.get("typeSpec", {}).get("type", "unknown")
                                all_codes.append(code)
                                code_to_ability_id[code] = ability_id
                                print(f"  Code: {code}, Name: {name}, Type: {prop_type}, Access: {access_mode}, AbilityID: {ability_id}")
                
                return all_codes, code_to_ability_id
            except json.JSONDecodeError as e:
                print(f"Error parsing model JSON: {e}")
                print(f"Raw model string: {model_str[:200]}...")
    
    return [], {}


def get_logs(
    access_token: str,
    code: str,                      # ← SINGLE code only
    start_time: int,
    end_time: int,
    size: int = 20,
    last_row_key: str | None = None,
):
    params = [
        ("codes", code),
        ("start_time", str(start_time)),
        ("end_time", str(end_time)),
        ("size", str(size)),
    ]

    if last_row_key:
        params.append(("last_row_key", last_row_key))

    params.sort(key=lambda x: x[0])

    query = urlencode(params, doseq=False)
    path = f"/v2.1/cloud/thing/{DEVICE_ID}/report-logs?{query}"

    t = ts_ms()
    sts = string_to_sign("GET", path, "")
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

    return requests.get(BASE_URL + path, headers=headers, timeout=15).json()


def get_operation_logs(
    access_token: str,
    start_time: int | None = None,
    end_time: int | None = None,
    size: int = 20,
):
    """
    Get device operation logs (control / command logs)
    Maps to: GET /v2.0/cloud/thing/{device_id}/logs
    """

    # Default to last 24 hours if not provided
    if end_time is None:
        end_time = int(time.time() * 1000)
    if start_time is None:
        start_time = end_time - (24 * 3600 * 1000)

    params = [
        ("end_time", str(end_time)),
        ("query_type", "1"),   # REQUIRED
        ("size", str(size)),
        ("start_time", str(start_time)),
        ("type", "1"),         # REQUIRED
    ]

    # Tuya requires lexicographic sorting
    params.sort(key=lambda x: x[0])

    query = urlencode(params, doseq=False)
    path = f"/v2.0/cloud/thing/{DEVICE_ID}/logs?{query}"

    t = ts_ms()
    sts = string_to_sign("GET", path, "")
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

    print("\n=== Requesting Operation Logs ===")
    print("GET", url)

    r = requests.get(url, headers=headers, timeout=15)
    return r.json()


if __name__ == "__main__":
    if not ACCESS_ID or not ACCESS_SECRET:
        raise SystemExit("Missing ACCESS_ID / ACCESS_SECRET")

    # ------------------------------------------------------------
    # 1. Authenticate
    # ------------------------------------------------------------
    token = get_token()
    print("✅ Access token acquired")

    # ------------------------------------------------------------
    # 2. Fetch device metadata (optional but useful)
    # ------------------------------------------------------------
    print("\n=== Device Info ===")
    try:
        get_details(token)
        get_state(token)
    except Exception as e:
        print("⚠️ Device info fetch failed:", e)

    # ------------------------------------------------------------
    # 3. Time window (IMPORTANT)
    # ------------------------------------------------------------
    now = int(time.time() * 1000)

    # DP report logs tolerate longer ranges on v2.1,
    # but 1–6 hours is safest
    report_start = now - (6 * 3600 * 1000)   # last 6 hours
    report_end = now

    # Operation logs are usually sparse
    op_start = now - (24 * 3600 * 1000)      # last 24 hours
    op_end = now

    print("\n=== Time Windows ===")
    print(f"Report logs: {report_start} → {report_end}")
    print(f"Operation logs: {op_start} → {op_end}")

    # ------------------------------------------------------------
    # 4. Fetch DP REPORT LOGS (v2.1) — single DP per request
    # ------------------------------------------------------------
    print("\n=== DP Report Logs (v2.1) ===")

    report_codes = [
        "anomaly_score",
        "event_type",
        "drift_flag",
    ]

    for code in report_codes:
        print(f"\n--- Fetching report logs for DP: {code} ---")
        try:
            res = get_logs(
                access_token=token,
                code=code,
                start_time=report_start,
                end_time=report_end,
                size=20,
            )

            if res.get("success"):
                logs = res["result"].get("logs", [])
                print(f"✅ {len(logs)} records")
                for item in logs[:5]:  # preview
                    print(
                        f"  - t={item['eventTime']} "
                        f"value={item['value']}"
                    )
            else:
                print("❌ Failed:", res)

        except Exception as e:
            print(f"❌ Error fetching report logs for {code}:", e)

    # ------------------------------------------------------------
    # 5. Fetch OPERATION LOGS (v2.0)
    # ------------------------------------------------------------
    print("\n=== Operation Logs (v2.0) ===")

    try:
        op_logs = get_operation_logs(
            access_token=token,
            start_time=op_start,
            end_time=op_end,
            size=20,
        )

        if op_logs.get("success"):
            logs = op_logs["result"].get("logs", [])
            print(f"✅ {len(logs)} operation records")

            if not logs:
                print("ℹ️ No device control operations found")
            else:
                for item in logs[:5]:
                    print(item)

        else:
            print("❌ Failed:", op_logs)

    except Exception as e:
        print("❌ Error fetching operation logs:", e)

    print("\n✅ Tuya log ingestion completed")

