#!/usr/bin/env python3
"""
SeedCore CLI — interactive shell for human-in-the-loop control.

Supports:
  facts                     : list current facts
  genfact <text>            : generate & store a new fact (UUID auto-assigned)
  setfact <id> <new text>   : update fact text
  delfact <id>              : delete a fact
  tasks                     : list tasks
  task <type> [desc]        : create & run a task (e.g. 'task memory_loop test')
  taskstatus <id>           : get status of a task
  exit / quit               : quit shell
"""

import os
import json
import uuid
import readline  # arrow-key history navigation
import requests

API_BASE = os.getenv("SEEDCORE_API", "http://127.0.0.1:8002")


# ------------------- FACTS -------------------
def list_facts():
    r = requests.get(f"{API_BASE}/facts")
    r.raise_for_status()
    data = r.json()
    items = data.get("items", [])
    if not items:
        print("📭 No facts yet.")
        return
    print(f"📖 Facts (total {data['total']}):")
    for f in items:
        print(f"  - {f['id']}: {f['text']}  tags={f.get('tags',[])}")


def gen_fact(text: str):
    payload = {"text": text, "metadata": {"source": "cli"}}
    r = requests.post(f"{API_BASE}/facts", json=payload)
    r.raise_for_status()
    f = r.json()
    print(f"✨ Created fact {f['id']}: {f['text']}")


def set_fact(fid: str, text: str):
    r = requests.patch(f"{API_BASE}/facts/{fid}", json={"text": text})
    if r.status_code == 404:
        print(f"❌ No fact {fid}")
        return
    r.raise_for_status()
    f = r.json()
    print(f"✅ Updated fact {fid}: {f['text']}")


def del_fact(fid: str):
    r = requests.delete(f"{API_BASE}/facts/{fid}")
    if r.status_code == 404:
        print(f"❌ No fact {fid}")
    else:
        print(f"🗑️ Deleted fact {fid}")


# ------------------- TASKS -------------------
def list_tasks():
    r = requests.get(f"{API_BASE}/tasks")
    r.raise_for_status()
    data = r.json()
    items = data.get("items", [])
    if not items:
        print("📭 No tasks yet.")
        return
    print(f"📝 Tasks (total {data['total']}):")
    for t in items:
        print(f"  - {t['id']} [{t['type']}] {t['status']} :: {t.get('description','')}")


def create_task(task_type: str, desc: str = ""):
    payload = {"type": task_type, "description": desc, "run_immediately": True}
    r = requests.post(f"{API_BASE}/tasks", json=payload)
    r.raise_for_status()
    t = r.json()
    print(f"🚀 Task {t['id']} [{t['type']}] created: {t['status']}")


def task_status(tid: str):
    r = requests.get(f"{API_BASE}/tasks/{tid}/status")
    if r.status_code == 404:
        print(f"❌ No task {tid}")
        return
    r.raise_for_status()
    s = r.json()
    print(f"📊 Task {s['id']}: {s['status']} (last update {s['updated_at']})")
    if s.get("error"):
        print(f"   ⚠️ Error: {s['error']}")


# ------------------- SHELL LOOP -------------------
def main():
    print("🎯 SeedCore Interactive Shell (v1.0)")
    print("Connected to", API_BASE)
    print("Type 'facts', 'genfact <text>', 'setfact <id> <text>', 'delfact <id>',")
    print("'tasks', 'task <type> [desc]', 'taskstatus <id>', 'exit'")
    print("=" * 70)

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
            if op == "facts":
                list_facts()
            elif op == "genfact" and len(parts) > 1:
                gen_fact(" ".join(parts[1:]))
            elif op == "setfact" and len(parts) > 2:
                set_fact(parts[1], " ".join(parts[2:]))
            elif op == "delfact" and len(parts) > 1:
                del_fact(parts[1])
            elif op == "tasks":
                list_tasks()
            elif op == "task" and len(parts) > 1:
                create_task(parts[1], " ".join(parts[2:]) if len(parts) > 2 else "")
            elif op == "taskstatus" and len(parts) > 1:
                task_status(parts[1])
            else:
                print(f"🤔 Unknown/invalid command: {cmd}")
        except Exception as e:
            print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
