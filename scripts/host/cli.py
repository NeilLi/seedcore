#!/usr/bin/env python3
"""
SeedCore CLI — interactive shell for human-in-the-loop control.

New in this version
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
import readline  # history + arrows
import requests
import difflib
import argparse
from datetime import datetime, timedelta, timezone

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
        print(f"🗑️ Deleted fact")

# ------------------- TASKS -------------------
def intelligent_task_creation(prompt: str):
    p = prompt.lower()
    payload = {"description": prompt, "run_immediately": True, "params": {}}
    if "plan" in p or "create a plan" in p:
        payload["type"] = "dspy.plan"
        payload["drift_score"] = 0.1
        payload["params"]["task_description"] = prompt
        print("🔍 Interpreted as a 'planning' task (low drift).")
    elif "analyze" in p or "reason about" in p:
        payload["type"] = "dspy.reason"
        payload["drift_score"] = 0.2
        if "incident" in p:
            parts = prompt.split()
            try:
                idx = parts.index("incident")
                payload["params"]["incident_id"] = parts[idx + 1]
            except Exception:
                pass
        print("🔍 Interpreted as a 'reasoning' task (low drift).")
    else:
        payload["type"] = "general_query"
        payload["drift_score"] = 0.9
        print("⚠️ Unrecognized pattern. Escalating with high drift score.")

    r = requests.post(f"{API_V1_BASE}/tasks", json=payload)
    r.raise_for_status()
    t = r.json()
    print(f"🚀 Task {t['id'][:8]} [{t['type']}] created with status '{t['status']}'")

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
            print(f"   ✅ Has result")
    except requests.RequestException as e:
        print(f"❌ Could not connect to API: {e}")

def show_help():
    print("🎯 SeedCore CLI Commands")
    print("=" * 60)
    print(" ask <prompt>              - Create and run a task from natural language")
    print(" facts                     - List all facts")
    print(" genfact <text>            - Create a new fact")
    print(" delfact <id>              - Delete a fact by ID")
    print(" tasks [--status S] [--type T] [--since V] [--limit N]")
    print("                           - List tasks with filters")
    print(" search <q> [--status S] [--type T] [--since V] [--limit N]")
    print("                           - Fuzzy search across id/type/description/result")
    print(" taskstatus <id>           - Detailed status (accepts short IDs)")
    print(" status <id>               - Quick status (accepts short IDs)")
    print(" health                    - Check API health status")
    print(" readyz                    - Check API readiness (including DB)")
    print(" help                      - Show this help")
    print(" exit / quit               - Exit")
    print("=" * 60)
    print("Examples:")
    print("  tasks --status running")
    print("  tasks --type general_query --since 24h --limit 10")
    print("  search tea --status completed")
    print("  ask analyze the incident 12345")
    print("")
    print("Note: All flags (--status, --type, --since, --limit) require values.")
    print("      Use 'tasks --status running' not 'tasks --status'")

# ------------------- SHELL LOOP -------------------
def main():
    print("🎯 SeedCore Interactive Shell (v1.6 — enhanced API integration)")
    print("Connected to", API_BASE)
    print("Commands: ask, facts, genfact, delfact, tasks, taskstatus, search, status, health, readyz, help, exit")
    print("=" * 70)

    SYSTEM_COMMANDS = {"facts", "genfact", "delfact", "tasks", "taskstatus", "search", "status", "health", "readyz", "help"}

    while True:
        try:
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
                if op == "facts":
                    list_facts()
                elif op == "genfact" and rest:
                    gen_fact(" ".join(rest))
                elif op == "delfact" and rest:
                    del_fact(rest[0])
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
                        q.append(rest[i]); i += 1
                    query = " ".join(q).strip()
                    search_tasks(query, rest[i:])
                elif op == "status" and rest:
                    quick_status(rest[0])
                elif op == "health":
                    check_health()
                elif op == "readyz":
                    check_readiness()
                elif op == "help":
                    show_help()
                else:
                    print("ℹ️ Try 'help' for usage.")
            else:
                # natural language or explicit 'ask'
                prompt = " ".join(rest) if op == "ask" else cmd
                intelligent_task_creation(prompt)
        except Exception as e:
            print(f"❌ An error occurred: {e}")

if __name__ == "__main__":
    main()
