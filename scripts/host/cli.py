#!/usr/bin/env python3
"""
SeedCore CLI — interactive shell for human-in-the-loop control.

New Features:
  - Intelligent 'ask' command to translate natural language into structured tasks.
  - Heuristic drift score to simulate OCPS gating for novel requests.

Supports:
  ask <natural language query> : Intelligently create and run a task.
  facts                        : list current facts
  genfact <text>               : generate & store a new fact
  delfact <id>                 : delete a fact
  tasks                        : list tasks
  taskstatus <id>              : get status of a task
  exit / quit                  : quit shell
"""
import os
import readline  # Enables arrow-key history navigation
import requests
from datetime import datetime

API_BASE = os.getenv("SEEDCORE_API", "http://127.0.0.1:8002")


# ------------------- Formatting Helpers -------------------
def _format_datetime(iso_string):
    """Nicely format ISO datetime strings for display."""
    if not iso_string:
        return "N/A"
    try:
        # Parse timezone-aware ISO string and convert to local time
        dt = datetime.fromisoformat(iso_string).astimezone()
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return iso_string

# ------------------- FACTS (No changes needed) -------------------
def list_facts():
    try:
        r = requests.get(f"{API_BASE}/facts")
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        if not items:
            print("📭 No facts yet.")
            return
        print(f"📖 Facts (total {data['total']}):")
        for f in items:
            print(f"  - {f['id'][:8]}: {f['text']}  tags={f.get('tags',[])}")
    except requests.RequestException as e:
        print(f"❌ Could not connect to API to list facts: {e}")

def gen_fact(text: str):
    payload = {"text": text, "metadata": {"source": "cli"}}
    r = requests.post(f"{API_BASE}/facts", json=payload)
    r.raise_for_status()
    f = r.json()
    print(f"✨ Created fact {f['id'][:8]}: {f['text']}")


def del_fact(fid: str):
    r = requests.delete(f"{API_BASE}/facts/{fid}")
    if r.status_code == 404:
        print(f"❌ No fact with ID starting with {fid}")
    else:
        r.raise_for_status()
        print(f"🗑️ Deleted fact")

# ------------------- TASKS -------------------

# --- NEW: Intelligent Task Creation ---
def intelligent_task_creation(prompt: str):
    """
    Parses a natural language prompt, assigns a task type, and estimates a drift score.
    """
    prompt_lower = prompt.lower()
    payload = {
        "description": prompt,
        "run_immediately": True,
        "params": {}
    }

    # --- Keyword-based mapping for "Fast-Path" style tasks ---
    if "plan" in prompt_lower or "create a plan" in prompt_lower:
        payload["type"] = "dspy.plan"
        payload["drift_score"] = 0.1  # Low drift for recognized patterns
        payload["params"]["task_description"] = prompt
        print("🔍 Interpreted as a 'planning' task (low drift).")

    elif "analyze" in prompt_lower or "reason about" in prompt_lower:
        payload["type"] = "dspy.reason"
        payload["drift_score"] = 0.2
        # Example of extracting a parameter
        if "incident" in prompt_lower:
             parts = prompt.split()
             try:
                 idx = parts.index("incident")
                 payload["params"]["incident_id"] = parts[idx + 1]
             except (ValueError, IndexError):
                 pass
        print("🔍 Interpreted as a 'reasoning' task (low drift).")

    else:
        # --- Fallback for "Escalation-Path" tasks ---
        # This is a novel task; assign a generic type and high drift score
        payload["type"] = "general_query"
        payload["drift_score"] = 0.9  # High drift for novel tasks
        print("⚠️ Unrecognized pattern. Escalating with high drift score.")

    # Send the structured task to the API
    r = requests.post(f"{API_BASE}/tasks", json=payload)
    r.raise_for_status()
    t = r.json()
    print(f"🚀 Task {t['id'][:8]} [{t['type']}] created with status '{t['status']}'")

# --- UPDATED: To display richer DB-backed data ---
def list_tasks():
    try:
        r = requests.get(f"{API_BASE}/tasks")
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        if not items:
            print("📭 No tasks yet.")
            return
        print(f"📝 Tasks (total {data['total']}):")
        for t in sorted(items, key=lambda x: x.get('created_at'), reverse=True):
            status = t.get('status', 'N/A').upper()
            desc = t.get('description', '')
            updated = _format_datetime(t.get('updated_at'))
            print(f"  - {t['id'][:8]} [{t['type']}] {status:<10} | {desc[:50]:<50} | Updated: {updated}")
    except requests.RequestException as e:
        print(f"❌ Could not connect to API to list tasks: {e}")

# --- UPDATED: To display richer DB-backed data ---
def task_status(tid: str):
    try:
        # Try to match prefix against all tasks
        r = requests.get(f"{API_BASE}/tasks")
        r.raise_for_status()
        items = r.json().get("items", [])
        matches = [t for t in items if t["id"].startswith(tid)]
        
        if not matches:
            print(f"❌ No task found with ID starting with {tid}")
            return
        if len(matches) > 1:
            print(f"⚠️ Multiple tasks match prefix {tid}:")
            for t in matches:
                print(f"   - {t['id']} [{t.get('type', 'N/A')}] {t.get('status', 'N/A')}")
            print(f"Please use a longer prefix to disambiguate.")
            return
            
        # Use the single matching task
        full_id = matches[0]["id"]
        print(f"🔍 Found task {full_id} (prefix: {tid})")
        
        # Now fetch the full task details
        r = requests.get(f"{API_BASE}/tasks/{full_id}")
        r.raise_for_status()
        t = r.json()
        
        status = t.get('status', 'N/A').upper()
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

# --- NEW: Search tasks by prefix or partial match ---
def search_tasks(query: str):
    """Search for tasks by ID prefix, type, or description."""
    try:
        r = requests.get(f"{API_BASE}/tasks")
        r.raise_for_status()
        items = r.json().get("items", [])
        
        # Search by ID prefix first
        id_matches = [t for t in items if t["id"].startswith(query)]
        
        # Search by type or description
        text_matches = [t for t in items if 
                       query.lower() in t.get('type', '').lower() or 
                       query.lower() in t.get('description', '').lower()]
        
        # Combine and deduplicate
        all_matches = list({t['id']: t for t in id_matches + text_matches}.values())
        
        if not all_matches:
            print(f"🔍 No tasks found matching '{query}'")
            return
            
        print(f"🔍 Found {len(all_matches)} task(s) matching '{query}':")
        for t in sorted(all_matches, key=lambda x: x.get('created_at'), reverse=True):
            status = t.get('status', 'N/A').upper()
            desc = t.get('description', '')[:50]
            created = _format_datetime(t.get('created_at'))
            print(f"  - {t['id'][:8]} [{t['type']}] {status:<10} | {desc:<50} | Created: {created}")
            
    except requests.RequestException as e:
        print(f"❌ Could not connect to API to search tasks: {e}")

# --- NEW: Convenience function for quick task status lookup ---
def quick_status(tid: str):
    """Quick status lookup - accepts short ID prefixes and shows minimal info."""
    try:
        # Try to match prefix against all tasks
        r = requests.get(f"{API_BASE}/tasks")
        r.raise_for_status()
        items = r.json().get("items", [])
        matches = [t for t in items if t["id"].startswith(tid)]
        
        if not matches:
            print(f"❌ No task found with ID starting with {tid}")
            return
        if len(matches) > 1:
            print(f"⚠️ Multiple tasks match prefix {tid}:")
            for t in matches[:3]:  # Show first 3 matches
                print(f"   - {t['id']} [{t.get('type', 'N/A')}] {t.get('status', 'N/A')}")
            if len(matches) > 3:
                print(f"   ... and {len(matches) - 3} more")
            print(f"Use 'taskstatus {tid}' for detailed info or 'search {tid}' to see all matches.")
            return
            
        # Show quick status for single match
        t = matches[0]
        status = t.get('status', 'N/A').upper()
        desc = t.get('description', '')[:40]
        updated = _format_datetime(t.get('updated_at'))
        
        print(f"📊 {t['id'][:8]} [{t['type']}] {status}")
        if desc:
            print(f"   {desc}")
        print(f"   Updated: {updated}")
        
        if t.get("error"):
            print(f"   🔴 Error: {t['error']}")
        elif t.get("result"):
            print(f"   ✅ Has result")
            
    except requests.RequestException as e:
        print(f"❌ Could not connect to API: {e}")

# --- NEW: Help command to show available commands ---
def show_help():
    """Show detailed help for all available commands."""
    print("🎯 SeedCore CLI Commands:")
    print("=" * 50)
    print("  ask <prompt>           - Create and run a task from natural language")
    print("  facts                   - List all facts in the system")
    print("  genfact <text>         - Generate a new fact")
    print("  delfact <id>           - Delete a fact by ID")
    print("  tasks                   - List all tasks")
    print("  taskstatus <id>        - Get detailed task status (accepts short IDs)")
    print("  status <id>            - Quick status lookup (accepts short IDs)")
    print("  search <query>         - Search tasks by ID prefix, type, or description")
    print("  help                    - Show this help message")
    print("  exit/quit              - Exit the CLI")
    print("=" * 50)
    print("Tips:")
    print("  - Use short ID prefixes (e.g., 'f9e9dfac' instead of full UUID)")
    print("  - Type natural language directly (e.g., 'analyze the incident')")
    print("  - Use 'search' to find tasks by type or description")


# ------------------- SHELL LOOP -------------------
def main():
    print("🎯 SeedCore Interactive Shell (v1.2 - Intelligent Default)")
    print("Connected to", API_BASE)
    print("Commands: ask, facts, genfact, delfact, tasks, taskstatus, search, status, exit")
    print("Examples:")
    print("  ask 'analyze the incident'     - Create and run a task")
    print("  taskstatus f9e9dfac           - Get detailed task status (accepts short IDs)")
    print("  status f9e9dfac               - Quick status lookup (accepts short IDs)")
    print("  search plan                    - Search tasks by type/description")
    print("  tasks                          - List all tasks")
    print("=" * 70)

    # --- NEW: Define a set of known system commands ---
    SYSTEM_COMMANDS = {"facts", "genfact", "delfact", "tasks", "taskstatus", "search", "status", "help"}

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
        op = parts[0]

        try:
            # --- UPDATED: Restructured logic ---
            if op in SYSTEM_COMMANDS:
                # Handle specific system commands as before
                if op == "facts":
                    list_facts()
                elif op == "genfact" and len(parts) > 1:
                    gen_fact(" ".join(parts[1:]))
                elif op == "delfact" and len(parts) > 1:
                    del_fact(parts[1])
                elif op == "tasks":
                    list_tasks()
                elif op == "taskstatus" and len(parts) > 1:
                    task_status(parts[1])
                elif op == "search" and len(parts) > 1:
                    search_tasks(" ".join(parts[1:]))
                elif op == "status" and len(parts) > 1:
                    quick_status(parts[1])
                elif op == "help":
                    show_help()
            else:
                # Default behavior: Treat the entire input as an 'ask' command
                # This handles explicit 'ask' and direct natural language queries
                prompt = cmd
                if op == "ask" and len(parts) > 1:
                    prompt = " ".join(parts[1:]) # Strip 'ask' if it was used
                
                intelligent_task_creation(prompt)

        except Exception as e:
            print(f"❌ An error occurred: {e}")


if __name__ == "__main__":
    main()