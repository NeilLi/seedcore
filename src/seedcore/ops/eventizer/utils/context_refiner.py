import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

class MultimodalContextRefiner:
    """
    Refines perception outputs into 'KG-ready' signals.
    Bridges the gap between raw Eventizer output and the Unified Memory View.
    """

    # Regex for relative time: "in 10 minutes", "in 2 hours"
    _re_relative_time = re.compile(r"in\s+(\d+)\s+(minute|min|hour|hr)s?", re.IGNORECASE)
    
    # Audio artifact cleanup (duplicates logic in normalizer but focused on semantic intent)
    _re_audio_noise = re.compile(r"\[.*?\]|\(.*?\)", re.IGNORECASE)

    @staticmethod
    def refine_voice_transcript(transcript: str, context_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Grounds relative time and cleans audio meta-tags.
        Example: "Pick up bags [cough] in 20 mins" -> 2026-01-06T14:21:11Z
        """
        if not context_time:
            context_time = datetime.now()

        # 1. Strip artifacts
        clean_text = MultimodalContextRefiner._re_audio_noise.sub("", transcript).strip()
        
        # 2. Extract and ground temporal references
        grounded_time = None
        match = MultimodalContextRefiner._re_relative_time.search(clean_text)
        if match:
            value = int(match.group(1))
            unit = match.group(2).lower()
            
            if "min" in unit:
                grounded_time = context_time + timedelta(minutes=value)
            elif "hour" in unit or "hr" in unit:
                grounded_time = context_time + timedelta(hours=value)

        return {
            "refined_text": clean_text,
            "grounded_timestamp": grounded_time.isoformat() if grounded_time else None,
            "has_temporal_intent": grounded_time is not None
        }

    @staticmethod
    def synthesize_vision_event(detections: List[Dict[str, Any]], camera_id: str) -> str:
        """
        Converts raw object detection lists into a narrative for the Vector Embedding.
        """
        if not detections:
            return f"No significant activity detected by camera {camera_id}."

        counts = {}
        for d in detections:
            obj = d.get("class", "object")
            counts[obj] = counts.get(obj, 0) + 1

        summary = ", ".join([f"{count} {obj}(s)" for obj, count in counts.items()])
        return f"Vision Alert: {summary} detected at {camera_id}."