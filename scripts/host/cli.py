#!/usr/bin/env python3
"""
SeedCore CLI — interactive shell for human-in-the-loop control.

New in v2.5
- voice <transcription> [key=value...] - Create CHAT task with multimodal voice envelope
- vision <scene_description> [type=action|query] [key=value...] - Create ACTION/QUERY task with multimodal vision envelope

Previous features:
- tasks --status <queued|running|completed|failed>
- tasks --type <task_type>
- tasks --since <1h|24h|2d|YYYY-MM-DD>
- tasks --limit N
- search <query>  (fuzzy across id/type/description/result) + same filters
- health / readyz - check API health and readiness

Still supports:
  ask <natural language>  : create & run a task
  facts / genfact / delfact
  taskstatus <id>         : detailed status (accepts short IDs)
  status <id>             : quick status
"""

import os
import re
import json
import requests  # pyright: ignore[reportMissingModuleSource]
import difflib
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from prompt_toolkit import prompt
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    PROMPT_TOOLKIT_AVAILABLE = False
    # Fallback to standard input if prompt_toolkit not available
    def prompt(prompt_text, **kwargs):
        return input(prompt_text)

API_BASE = os.getenv("SEEDCORE_API", "http://127.0.0.1:8002")
API_V1_BASE = f"{API_BASE}/api/v1"

# ------------------- Helpers -------------------
def _format_datetime(iso_string):
    if not iso_string:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_string).astimezone()
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return iso_string

def _now():
    return datetime.now(timezone.utc)

def _parse_since(val: str) -> datetime | None:
    """Accepts '1h', '24h', '2d', '30m', or ISO date 'YYYY-MM-DD'."""
    if not val:
        return None
    val = val.strip().lower()
    m = re.fullmatch(r"(\d+)([smhd])", val)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"s": timedelta(seconds=n),
                 "m": timedelta(minutes=n),
                 "h": timedelta(hours=n),
                 "d": timedelta(days=n)}[unit]
        return _now() - delta
    # Try plain date
    try:
        return datetime.fromisoformat(val).replace(tzinfo=timezone.utc)
    except Exception:
        return None

def _parse_quoted_string(args: list[str]) -> tuple[str, list[str]]:
    """
    Parse a quoted string from the beginning of args list.
    
    Handles both single and double quotes. If the first arg starts with a quote,
    collects subsequent args until the closing quote is found.
    
    Args:
        args: List of arguments (may include quoted strings split by spaces)
    
    Returns:
        Tuple of (parsed_string, remaining_args)
    """
    if not args:
        return "", []
    
    first_arg = args[0]
    
    # Check if first arg starts with a quote
    if first_arg.startswith("'") or first_arg.startswith('"'):
        quote_char = first_arg[0]
        
        # Check if the quote is already closed in the first arg (single-word quoted string)
        if len(first_arg) > 1 and first_arg.endswith(quote_char):
            # Single-word quoted string like 'Hello' or "Hello"
            parsed = first_arg[1:-1]  # Remove both opening and closing quotes
            return parsed, args[1:]
        
        # Multi-word quoted string: collect parts until closing quote
        # Remove opening quote from first part
        parts = [first_arg[1:]]
        
        # Collect parts until we find closing quote
        for i, arg in enumerate(args[1:], start=1):
            if arg.endswith(quote_char):
                # Found closing quote, remove it and join
                parts.append(arg[:-1])
                parsed = " ".join(parts)
                return parsed, args[i+1:]
            else:
                parts.append(arg)
        
        # No closing quote found in remaining args, return as-is (malformed but don't crash)
        parsed = " ".join(parts)
        return parsed, args[len(parts):]
    
    # No quote, return first arg as-is
    return args[0], args[1:]

def _parse_task_args(argv):
    """Parse task/search command arguments using argparse for robust flag handling."""
    parser = argparse.ArgumentParser(prog="tasks", add_help=False)
    parser.add_argument("--status", type=str, help="Filter by status (e.g., running, completed, queued)")
    parser.add_argument("--type", type=str, help="Filter by task type")
    parser.add_argument("--since", type=str, help="Filter by time (e.g., 24h, 7d, 2024-01-01)")
    parser.add_argument("--limit", type=int, help="Limit number of results")
    
    try:
        return parser.parse_args(argv)
    except SystemExit:
        # argparse will exit on invalid args, but we want to handle this gracefully
        return None

def _fetch_tasks():
    r = requests.get(f"{API_V1_BASE}/tasks")
    r.raise_for_status()
    data = r.json()
    return data.get("items", []), data.get("total", len(data))

def _status_matches(task_status: str, want: str) -> bool:
    if not want:
        return True
    s = (task_status or "").lower()
    w = want.lower()
    return s.startswith(w) or s == w

def _type_matches(task_type: str, want: str) -> bool:
    if not want:
        return True
    t = (task_type or "").lower()
    w = want.lower()
    return t == w or w in t

def _since_matches(updated_at: str, since_dt: datetime | None) -> bool:
    if not since_dt:
        return True
    try:
        dt = datetime.fromisoformat(updated_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= since_dt
    except Exception:
        return True  # don't drop if we can't parse

def _limit(items, n):
    try:
        n = int(n)
        if n > 0:
            return items[:n]
    except Exception:
        pass
    return items

def _task_str_result(task) -> str:
    res = task.get("result")
    if res is None:
        return ""
    try:
        return json.dumps(res, ensure_ascii=False)
    except Exception:
        return str(res)

# ------------------- HEALTH CHECKS -------------------
def check_health():
    """Check API health status."""
    try:
        r = requests.get(f"{API_BASE}/health")
        r.raise_for_status()
        data = r.json()
        print(f"🏥 Health: {data.get('status', 'unknown')}")
        print(f"   Service: {data.get('service', 'unknown')}")
        print(f"   Version: {data.get('version', 'unknown')}")
    except requests.RequestException as e:
        print(f"❌ Health check failed: {e}")

def check_readiness():
    """Check API readiness (including database connectivity)."""
    try:
        r = requests.get(f"{API_BASE}/readyz")
        r.raise_for_status()
        data = r.json()
        print(f"✅ Readiness: {data.get('status', 'unknown')}")
        if 'deps' in data:
            for dep, status in data['deps'].items():
                print(f"   {dep}: {status}")
    except requests.RequestException as e:
        print(f"❌ Readiness check failed: {e}")


# ------------------- FACTS -------------------
def list_facts():
    try:
        r = requests.get(f"{API_V1_BASE}/facts")
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        if not items:
            print("📭 No facts yet.")
            return
        print(f"📖 Facts (total {data.get('total', len(items))}):")
        for f in items:
            print(f"  - {f['id'][:8]}: {f['text']}  tags={f.get('tags',[])}")
    except requests.RequestException as e:
        print(f"❌ Could not connect to API to list facts: {e}")

def gen_fact(text: str):
    payload = {"text": text, "metadata": {"source": "cli"}}
    r = requests.post(f"{API_V1_BASE}/facts", json=payload)
    r.raise_for_status()
    f = r.json()
    print(f"✨ Created fact {f['id'][:8]}: {f['text']}")

def del_fact(fid: str):
    r = requests.delete(f"{API_V1_BASE}/facts/{fid}")
    if r.status_code == 404:
        print(f"❌ No fact with ID starting with {fid}")
    else:
        r.raise_for_status()
        print("🗑️ Deleted fact")

# ------------------- TASKS -------------------
def create_task(task_type: str, description: str, params: dict | None = None, domain: str | None = None):
    """
    Explicit task creation helper.
    
    Args:
        task_type: TaskType value (query, action, graph, maintenance, chat)
        description: Human-readable description
        params: Optional params dict
        domain: Optional domain/namespace (e.g., "device", "robot")
    """
    payload = {
        "type": task_type,
        "description": description,
        "params": params or {},
        "run_immediately": True,
    }
    if domain:
        payload["domain"] = domain
    
    try:
        r = requests.post(f"{API_V1_BASE}/tasks", json=payload)
        r.raise_for_status()
        t = r.json()
        print(f"🚀 Task {t['id'][:8]} [{t['type']}] created with status '{t['status']}'")
    except requests.RequestException as e:
        print(f"❌ Failed to create task: {e}")


def query_command(args):
    """query <description> - Create a QUERY task (reasoning, analysis, planning)"""
    if not args:
        print("Usage: query <description>")
        print("Example: query 'analyze yesterday's energy usage'")
        return
    
    description = " ".join(args)
    create_task(
        task_type="query",
        description=description,
        params={"task_description": description},
    )


def device_command(args):
    """device <on|off> <device_type> [key=value ...] - Create an ACTION task for device control"""
    if len(args) < 2:
        print("Usage: device <on|off> <device_type> [key=value ...]")
        print("Examples:")
        print("  device on light room=1203")
        print("  device off hvac room=1203")
        print("  device on light room=1203 brightness=50")
        return
    
    action = args[0].lower()
    if action not in ("on", "off"):
        print(f"❌ Invalid action '{action}'. Must be 'on' or 'off'")
        return
    
    device_type = args[1].lower()
    
    # Parse key=value pairs
    kv = {}
    for arg in args[2:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            kv[k] = v
    
    description = f"{action} {device_type}"
    if kv:
        description += " " + " ".join(f"{k}={v}" for k, v in kv.items())
    
    create_task(
        task_type="action",
        description=description,
        domain="device",
        params={
            "domain": "device",
            "action": action,
            "device": device_type,
            **kv,
        },
    )


def robot_command(args):
    """robot <dispatch|stop> <task> [key=value ...] - Create an ACTION task for robot control"""
    if len(args) < 2:
        print("Usage: robot <dispatch|stop> <task> [key=value ...]")
        print("Examples:")
        print("  robot dispatch cleaning room=1203")
        print("  robot stop cleaning robot=cleaner-2")
        return
    
    action = args[0].lower()
    if action not in ("dispatch", "stop"):
        print(f"❌ Invalid action '{action}'. Must be 'dispatch' or 'stop'")
        return
    
    task = args[1].lower()
    
    # Parse key=value pairs
    kv = {}
    for arg in args[2:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            kv[k] = v
    
    description = f"robot {action} {task}"
    if kv:
        description += " " + " ".join(f"{k}={v}" for k, v in kv.items())
    
    create_task(
        task_type="action",
        description=description,
        domain="robot",
        params={
            "domain": "robot",
            "action": action,
            "task": task,
            **kv,
        },
    )


def graph_command(args):
    """graph <operation> [args...] - Create a GRAPH task for knowledge graph operations"""
    if not args:
        print("Usage: graph <operation> [args...]")
        print("Examples:")
        print("  graph find rooms with hvac_alarm")
        print("  graph relate guest=alice preference=quiet")
        return
    
    description = " ".join(args)
    create_task(
        task_type="graph",
        description=description,
        params={"operation": args[0], "args": args[1:]},
    )


def maintenance_command(args):
    """maint <operation> [args...] - Create a MAINTENANCE task for system operations"""
    if not args:
        print("Usage: maint <operation> [args...]")
        print("Examples:")
        print("  maint check devices")
        print("  maint restart robot cleaner-1")
        print("  maint drain queue orchestration")
        return
    
    description = " ".join(args)
    create_task(
        task_type="maintenance",
        description=description,
        params={"operation": args[0], "args": args[1:]},
    )


def voice_command(args):
    """voice <transcription> [key=value ...] - Create a CHAT task with multimodal voice envelope"""
    if not args:
        print("Usage: voice <transcription> [key=value ...]")
        print("Examples:")
        print("  voice 'Turn off the lights in the lobby' media_uri=s3://hotel-assets/audio/clip_99.wav")
        print("  voice 'Set temperature to 72' media_uri=s3://hotel-assets/audio/clip_100.wav location_context=lobby_area_01 confidence=0.98")
        print("  voice 'Hello' media_uri=s3://hotel-assets/audio/clip_101.wav transcription_engine=whisper-v3 duration_seconds=2.5 language=en-US is_real_time=true")
        print("")
        print("Required: transcription (first arg), media_uri")
        print("Optional: transcription_engine, confidence, duration_seconds, language, location_context, is_real_time, ttl_seconds")
        return
    
    # Parse quoted transcription string (handles multi-word transcriptions)
    transcription, remaining_args = _parse_quoted_string(args)
    
    # Parse key=value pairs from remaining args
    kv = {}
    for arg in remaining_args:
        if "=" in arg:
            k, v = arg.split("=", 1)
            kv[k] = v
    
    # Required fields
    if "media_uri" not in kv:
        print("❌ Required: media_uri (e.g., media_uri=s3://hotel-assets/audio/clip_99.wav)")
        return
    
    # Build multimodal envelope
    multimodal = {
        "source": "voice",
        "media_uri": kv.pop("media_uri"),
        "transcription": transcription,
    }
    
    # Optional voice-specific fields
    for field in ["transcription_engine", "confidence", "duration_seconds", "language", "location_context", "is_real_time", "ttl_seconds"]:
        if field in kv:
            value = kv.pop(field)
            # Type conversions
            if field == "confidence":
                try:
                    multimodal[field] = float(value)
                except ValueError:
                    print(f"⚠️ Warning: confidence must be a float, ignoring '{value}'")
            elif field == "duration_seconds":
                try:
                    multimodal[field] = float(value)
                except ValueError:
                    print(f"⚠️ Warning: duration_seconds must be a float, ignoring '{value}'")
            elif field == "ttl_seconds":
                try:
                    multimodal[field] = int(value)
                except ValueError:
                    print(f"⚠️ Warning: ttl_seconds must be an integer, ignoring '{value}'")
            elif field == "is_real_time":
                multimodal[field] = value.lower() in ("true", "1", "yes", "on")
            else:
                multimodal[field] = value
    
    # Build params with multimodal envelope and chat envelope
    params = {
        "multimodal": multimodal,
        "chat": {
            "message": transcription
        }
    }
    
    # Add any remaining kv pairs to params (for extensibility)
    if kv:
        params.update(kv)
    
    create_task(
        task_type="chat",
        description=transcription,
        params=params,
    )


def vision_command(args):
    """vision <scene_description> [type=action|query] [key=value ...] - Create an ACTION/QUERY task with multimodal vision envelope"""
    if len(args) < 1:
        print("Usage: vision <scene_description> [type=action|query] [key=value ...]")
        print("Examples:")
        print("  vision 'Person detected near Room 101' media_uri=s3://hotel-assets/video/camera_101.mp4")
        print("  vision 'Person detected near Room 101' type=action media_uri=s3://hotel-assets/video/camera_101.mp4 camera_id=camera_101 confidence=0.92")
        print("  vision 'Visual scene analysis' type=query media_uri=s3://hotel-assets/video/scene.mp4 detection_engine=yolo-v8 location_context=room_101_corridor")
        print("  vision 'Security alert' type=action media_uri=s3://hotel-assets/video/alert.mp4 is_real_time=true ttl_seconds=60 parent_stream_id=stream_camera_101")
        print("")
        print("Required: scene_description (first arg), media_uri")
        print("Optional: type (action|query, default: action), detection_engine, confidence, timestamp, camera_id, location_context, is_real_time, ttl_seconds, parent_stream_id, detected_objects (JSON)")
        return
    
    # Parse quoted scene description string (handles multi-word descriptions)
    scene_description, remaining_args = _parse_quoted_string(args)
    
    # Parse key=value pairs from remaining args
    kv = {}
    for arg in remaining_args:
        if "=" in arg:
            k, v = arg.split("=", 1)
            kv[k] = v
    
    # Determine task type (default: action)
    task_type = kv.pop("type", "action").lower()
    if task_type not in ("action", "query"):
        print("⚠️ Warning: type must be 'action' or 'query', defaulting to 'action'")
        task_type = "action"
    
    # Required fields
    if "media_uri" not in kv:
        print("❌ Required: media_uri (e.g., media_uri=s3://hotel-assets/video/camera_101.mp4)")
        return
    
    # Build multimodal envelope
    multimodal = {
        "source": "vision",
        "media_uri": kv.pop("media_uri"),
        "scene_description": scene_description,
    }
    
    # Optional vision-specific fields
    for field in ["detection_engine", "confidence", "timestamp", "camera_id", "location_context", "is_real_time", "ttl_seconds", "parent_stream_id", "detected_objects"]:
        if field in kv:
            value = kv.pop(field)
            # Type conversions
            if field == "confidence":
                try:
                    multimodal[field] = float(value)
                except ValueError:
                    print(f"⚠️ Warning: confidence must be a float, ignoring '{value}'")
            elif field == "ttl_seconds":
                try:
                    multimodal[field] = int(value)
                except ValueError:
                    print(f"⚠️ Warning: ttl_seconds must be an integer, ignoring '{value}'")
            elif field == "is_real_time":
                multimodal[field] = value.lower() in ("true", "1", "yes", "on")
            elif field == "detected_objects":
                # Try to parse as JSON
                try:
                    multimodal[field] = json.loads(value)
                except json.JSONDecodeError:
                    print(f"⚠️ Warning: detected_objects must be valid JSON, ignoring '{value}'")
            else:
                multimodal[field] = value
    
    # Build params with multimodal envelope
    params = {
        "multimodal": multimodal
    }
    
    # Add any remaining kv pairs to params (for extensibility)
    if kv:
        params.update(kv)
    
    create_task(
        task_type=task_type,
        description=scene_description,
        params=params,
    )

def _print_task_row(t, prefix="  - "):
    status = (t.get('status') or 'N/A').upper()
    desc = t.get('description', '')
    updated = _format_datetime(t.get('updated_at'))
    
    # Truncate description more intelligently - try to break at word boundaries
    if len(desc) > 50:
        # Try to find a good break point around 50 characters
        trunc_desc = desc[:47] + "..."
    else:
        trunc_desc = desc
    
    # Use dynamic width for better alignment
    print(f"{prefix}{t['id'][:8]} [{t.get('type','N/A')}] {status:<10} | {trunc_desc:<53} | Updated: {updated}")

def list_tasks_with_filters(args):
    """tasks [--status X] [--type Y] [--since 24h|YYYY-MM-DD] [--limit N]"""
    parsed_args = _parse_task_args(args)
    if parsed_args is None:
        print("❌ Invalid arguments. Use: tasks [--status <status>] [--type <type>] [--since <time>] [--limit <number>]")
        return
    
    want_status = parsed_args.status
    want_type   = parsed_args.type
    since_dt    = _parse_since(parsed_args.since or "")
    limit_n     = parsed_args.limit

    try:
        items, total = _fetch_tasks()
        # newest first
        items = sorted(items, key=lambda x: x.get('created_at') or "", reverse=True)

        # apply filters
        filtered = [
            t for t in items
            if _status_matches(t.get("status",""), want_status)
            and _type_matches(t.get("type",""), want_type)
            and _since_matches(t.get("updated_at") or t.get("created_at",""), since_dt)
        ]
        if limit_n:
            filtered = _limit(filtered, limit_n)

        print(f"📝 Tasks (showing {len(filtered)}/{total}"
              f"{' | status='+str(want_status) if want_status else ''}"
              f"{' | type='+str(want_type) if want_type else ''}"
              f"{' | since set' if since_dt else ''}"
              f"{' | limit='+str(limit_n) if limit_n else ''}):")
        for t in filtered:
            _print_task_row(t)
        if not filtered:
            print("  (no matches)")
    except requests.RequestException as e:
        print(f"❌ Could not connect to API to list tasks: {e}")

def task_status(tid: str):
    try:
        items, _ = _fetch_tasks()
        matches = [t for t in items if t["id"].startswith(tid)]
        if not matches:
            print(f"❌ No task found with ID starting with {tid}")
            return
        if len(matches) > 1:
            print(f"⚠️ Multiple tasks match prefix {tid}:")
            for t in matches:
                print(f"   - {t['id']} [{t.get('type','N/A')}] {t.get('status','N/A')}")
            print("Use a longer prefix to disambiguate.")
            return

        full_id = matches[0]["id"]
        r = requests.get(f"{API_V1_BASE}/tasks/{full_id}")
        r.raise_for_status()
        t = r.json()

        status = (t.get('status') or 'N/A').upper()
        updated = _format_datetime(t.get('updated_at'))
        print(f"📊 Task {t['id'][:8]}")
        print(f"   Status:    {status}")
        print(f"   Type:      {t.get('type')}")
        print(f"   Updated:   {updated}")
        print(f"   Drift:     {t.get('drift_score')}")
        if t.get("error"):
            print(f"   🔴 Error: {t['error']}")
        if t.get("result"):
            print(f"   ✅ Result: {t['result']}")
    except requests.RequestException as e:
        print(f"❌ Could not connect to API to get task status: {e}")

def _fuzzy_score(haystack: str, needle: str) -> float:
    return difflib.SequenceMatcher(None, haystack.lower(), needle.lower()).ratio()

def search_tasks(query: str, args=None):
    """search <query> [--status X] [--type Y] [--since ...] [--limit N]"""
    parsed_args = _parse_task_args(args or [])
    if parsed_args is None:
        print("❌ Invalid arguments. Use: search <query> [--status <status>] [--type <type>] [--since <time>] [--limit <number>]")
        return
    
    want_status = parsed_args.status
    want_type   = parsed_args.type
    since_dt    = _parse_since(parsed_args.since or "")
    limit_n     = parsed_args.limit

    try:
        items, _ = _fetch_tasks()
        # candidate score based on id/type/description/result (max of fields)
        scored = []
        for t in items:
            fields = [
                t.get("id",""),
                t.get("type",""),
                t.get("description",""),
                _task_str_result(t),
            ]
            score = max((_fuzzy_score(f, query) for f in fields if f), default=0.0)
            if score >= 0.45:  # default fuzzy threshold
                scored.append((score, t))

        # newest first, then by score
        scored.sort(key=lambda s: (s[1].get('created_at') or "", s[0]), reverse=True)
        filtered = [
            t for (_, t) in scored
            if _status_matches(t.get("status",""), want_status)
            and _type_matches(t.get("type",""), want_type)
            and _since_matches(t.get("updated_at") or t.get("created_at",""), since_dt)
        ]
        if limit_n:
            filtered = _limit(filtered, limit_n)

        if not filtered:
            print(f"🔍 No tasks found matching '{query}'")
            return

        print(f"🔍 Found {len(filtered)} task(s) matching '{query}'"
              f"{' | status='+str(want_status) if want_status else ''}"
              f"{' | type='+str(want_type) if want_type else ''}"
              f"{' | since set' if since_dt else ''}"
              f"{' | limit='+str(limit_n) if limit_n else ''}:")
        for t in filtered:
            created = _format_datetime(t.get('created_at'))
            status = (t.get('status') or 'N/A').upper()
            desc = t.get('description','')[:50]
            print(f"  - {t['id'][:8]} [{t.get('type','N/A')}] {status:<10} | {desc:<50} | Created: {created}")

    except requests.RequestException as e:
        print(f"❌ Could not connect to API to search tasks: {e}")

def quick_status(tid: str):
    try:
        items, _ = _fetch_tasks()
        matches = [t for t in items if t["id"].startswith(tid)]
        if not matches:
            print(f"❌ No task found with ID starting with {tid}")
            return
        if len(matches) > 1:
            print(f"⚠️ Multiple tasks match prefix {tid}:")
            for t in matches[:3]:
                print(f"   - {t['id']} [{t.get('type','N/A')}] {t.get('status','N/A')}")
            if len(matches) > 3:
                print(f"   ... and {len(matches)-3} more")
            print(f"Use 'taskstatus {tid}' for details or 'search {tid}'.")
            return
        t = matches[0]
        status = (t.get('status') or 'N/A').upper()
        desc = t.get('description', '')[:40]
        updated = _format_datetime(t.get('updated_at'))
        print(f"📊 {t['id'][:8]} [{t.get('type','N/A')}] {status}")
        if desc:
            print(f"   {desc}")
        print(f"   Updated: {updated}")
        if t.get("error"):
            print(f"   🔴 Error: {t['error']}")
        elif t.get("result"):
            print("   ✅ Has result")
    except requests.RequestException as e:
        print(f"❌ Could not connect to API: {e}")

def show_help():
    print("🎯 SeedCore CLI Commands")
    print("=" * 70)
    print("Task Creation (Explicit):")
    print("  ask <prompt>              - Create QUERY task from natural language")
    print("  query <description>       - Create QUERY task (reasoning, analysis)")
    print("  device <on|off> <type> [key=value...]")
    print("                           - Create ACTION task for device control")
    print("  robot <dispatch|stop> <task> [key=value...]")
    print("                           - Create ACTION task for robot control")
    print("  graph <operation> [args...]")
    print("                           - Create GRAPH task for knowledge operations")
    print("  maint <operation> [args...]")
    print("                           - Create MAINTENANCE task for system ops")
    print("  voice <transcription> [key=value...]")
    print("                           - Create CHAT task with multimodal voice envelope")
    print("  vision <scene_description> [type=action|query] [key=value...]")
    print("                           - Create ACTION/QUERY task with multimodal vision envelope")
    print("")
    print("Task Inspection:")
    print("  tasks [--status S] [--type T] [--since V] [--limit N]")
    print("                           - List tasks with filters")
    print("  search <q> [--status S] [--type T] [--since V] [--limit N]")
    print("                           - Fuzzy search across id/type/description/result")
    print("  taskstatus <id>           - Detailed status (accepts short IDs)")
    print("  status <id>               - Quick status (accepts short IDs)")
    print("")
    print("Facts:")
    print("  facts                     - List all facts")
    print("  genfact <text>            - Create a new fact")
    print("  delfact <id>              - Delete a fact by ID")
    print("")
    print("System:")
    print("  health                    - Check API health status")
    print("  readyz                    - Check API readiness (including DB)")
    print("  help                      - Show this help")
    print("  exit / quit               - Exit")
    print("=" * 70)
    print("Examples:")
    print("  query analyze yesterday's energy usage")
    print("  device on light room=1203")
    print("  device off hvac room=1203 brightness=0")
    print("  robot dispatch cleaning room=1203")
    print("  robot stop cleaning robot=cleaner-2")
    print("  graph find rooms with hvac_alarm")
    print("  maint check devices")
    print("  voice 'Turn off the lights' media_uri=s3://hotel-assets/audio/clip_99.wav")
    print("  vision 'Person detected near Room 101' media_uri=s3://hotel-assets/video/camera_101.mp4")
    print("  vision 'Visual analysis' type=query media_uri=s3://hotel-assets/video/scene.mp4 camera_id=camera_101")
    print("  tasks --status running --type action")
    print("  tasks --type action --since 24h --limit 10")
    print("")
    print("Note: All flags (--status, --type, --since, --limit) require values.")
    print("      Use 'tasks --status running' not 'tasks --status'")

# ------------------- SHELL LOOP -------------------
def main():
    print("🎯 SeedCore Interactive Shell (v2.5 — multimodal support)")
    print("Connected to", API_BASE)
    print("Commands: ask, query, device, robot, graph, maint, voice, vision, facts, tasks, search, status, health, readyz, help, exit")
    print("=" * 70)

    SYSTEM_COMMANDS = {
        "ask", "query",
        "device", "robot", "graph", "maint",
        "voice", "vision",
        "facts", "genfact", "delfact",
        "tasks", "taskstatus", "search", "status",
        "health", "readyz", "help"
    }

    # Set up command history if prompt_toolkit is available
    history = None
    auto_suggest = None
    if PROMPT_TOOLKIT_AVAILABLE:
        try:
            history_file = Path.home() / ".seedcore_cli_history"
            history_file.parent.mkdir(parents=True, exist_ok=True)
            history = FileHistory(str(history_file))
            auto_suggest = AutoSuggestFromHistory()
        except Exception as e:
            # Fallback if history setup fails
            print(f"⚠️ Warning: Could not initialize command history: {e}")

    while True:
        try:
            if PROMPT_TOOLKIT_AVAILABLE and history:
                cmd = prompt(
                    "SeedCore> ",
                    history=history,
                    auto_suggest=auto_suggest,
                ).strip()
            else:
                cmd = input("SeedCore> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Exiting SeedCore CLI")
            break
        if not cmd:
            continue
        if cmd in {"exit", "quit"}:
            break

        parts = cmd.split()
        op, rest = parts[0], parts[1:]

        try:
            if op in SYSTEM_COMMANDS:
                # Task creation commands
                if op in ("ask", "query"):
                    if not rest:
                        print("Usage: {} <description>".format(op))
                        print("Example: {} 'analyze yesterday's energy usage'".format(op))
                    else:
                        query_command(rest)
                elif op == "device":
                    device_command(rest)
                elif op == "robot":
                    robot_command(rest)
                elif op == "graph":
                    graph_command(rest)
                elif op == "maint":
                    maintenance_command(rest)
                elif op == "voice":
                    voice_command(rest)
                elif op == "vision":
                    vision_command(rest)
                # Facts commands
                elif op == "facts":
                    list_facts()
                elif op == "genfact" and rest:
                    gen_fact(" ".join(rest))
                elif op == "delfact" and rest:
                    del_fact(rest[0])
                # Task inspection commands
                elif op == "tasks":
                    list_tasks_with_filters(rest)
                elif op == "taskstatus" and rest:
                    task_status(rest[0])
                elif op == "search" and rest:
                    # everything up to the first flag token is the query
                    # e.g. search tea with milk --status completed
                    q = []
                    i = 0
                    while i < len(rest) and not rest[i].startswith("--"):
                        q.append(rest[i])
                        i += 1
                    query = " ".join(q).strip()
                    search_tasks(query, rest[i:])
                elif op == "status" and rest:
                    quick_status(rest[0])
                # System commands
                elif op == "health":
                    check_health()
                elif op == "readyz":
                    check_readiness()
                elif op == "help":
                    show_help()
                else:
                    print("ℹ️ Try 'help' for usage.")
            else:
                # Unknown command - treat as natural language query (backward compatibility)
                print(f"⚠️ Unknown command '{op}'. Treating as natural language query.")
                print("💡 Tip: Use explicit commands for better control:")
                print("   - 'query <description>' for reasoning/analysis")
                print("   - 'device <on|off> <type> [key=value...]' for device control")
                print("   - 'robot <dispatch|stop> <task> [key=value...]' for robot control")
                print("   - 'voice <transcription> [key=value...]' for voice commands")
                print("   - 'vision <scene_description> [type=action|query] [key=value...]' for vision tasks")
                query_command([cmd])
        except Exception as e:
            print(f"❌ An error occurred: {e}")

if __name__ == "__main__":
    main()
