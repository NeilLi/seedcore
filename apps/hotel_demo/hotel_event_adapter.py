# apps/hotel_demo/hotel_event_adapter.py
from __future__ import annotations
from typing import Dict, Any, Optional

ALLOWED = {
    "ui.hotspot.entered",
    "ui.voice.transcript.final",
    "ui.button.clicked",
    "sim.room.occupancy.changed",
    "sim.agent.state.changed",
}

class HotelAdapter:
    def __init__(self):
        self._hotspot_by_session: Dict[str, str] = {}

    def should_accept(self, event: Dict[str, Any]) -> bool:
        return event.get("type") in ALLOWED

    def handle(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        etype = event["type"]
        session_id = str(event.get("sessionId") or "unknown")
        payload = event.get("payload") or {}

        if etype == "ui.hotspot.entered":
            hid = payload.get("hotspotId")
            if hid:
                self._hotspot_by_session[session_id] = str(hid)
            return None  # consume only

        if etype == "ui.voice.transcript.final":
            transcript = (payload.get("transcript") or "").strip()
            if not transcript:
                return None

            return {
                "type": "query",
                "description": transcript,
                "params": {
                    "domain": "hotel",
                    "sessionId": session_id,
                    "hotspotId": self._hotspot_by_session.get(session_id),
                    "event": event,
                },
                "run_immediately": True,
                "domain": "hotel",
            }

        # Optional others:
        if etype == "ui.button.clicked":
            button_id = str(payload.get("buttonId") or "")
            if not button_id:
                return None
            return {
                "type": "action",
                "description": f"button:{button_id}",
                "params": {"sessionId": session_id, "buttonId": button_id, "event": event},
                "run_immediately": True,
                "domain": "hotel",
            }

        return None
