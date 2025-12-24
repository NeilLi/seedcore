import os


class TuyaConfig:
    def __init__(self):
        self.enabled = os.getenv("TUYA_ENABLED", "false").lower() == "true"

        if not self.enabled:
            return

        self.region = os.getenv("TUYA_REGION", "sg")
        self.api_base = os.getenv("TUYA_API_BASE")
        self.access_id = os.getenv("TUYA_ACCESS_ID")
        self.access_secret = os.getenv("TUYA_ACCESS_SECRET")
        self.project_code = os.getenv("TUYA_PROJECT_CODE", "seedcore")

        missing = [
            k
            for k, v in {
                "TUYA_API_BASE": self.api_base,
                "TUYA_ACCESS_ID": self.access_id,
                "TUYA_ACCESS_SECRET": self.access_secret,
            }.items()
            if not v
        ]

        if missing:
            raise RuntimeError(
                f"Tuya enabled but missing env vars: {', '.join(missing)}"
            )
