#!/usr/bin/env python3
"""
SeedCore CLI — management interface for tasks, services, and HGNN graph.

Architecture:
- SeedCore API: SEEDCORE_API (default http://127.0.0.1:8002) - Main API server
- Ray Serve Services: http://127.0.0.1:8000 - Coordinator, Ops, ML, Cognitive services
- Postgres: PG_DSN or SEEDCORE_PG_DSN (optional; enables HGNN ops)

Features:
- Task Management: create, list, search, status via SeedCore API
- Service Health: check SeedCore API health and readiness
- Eventizer Testing: test text processing via /ops endpoint
- Agent Graph: ensure nodes (agent/organ/model/service/skill/policy)
- HGNN edges: query 1-hop edges from unified hgnn_edges view

Service Integration:
- Uses SeedCore API endpoints (/api/v1/*) for task operations
- Uses Ray Serve endpoints (/ops/*, /pipeline/*) for service operations
- All communication goes through proper HTTP clients, not direct Ray handles
"""

import os
import re
import json
import argparse
import difflib
from datetime import datetime, timedelta, timezone

import requests

# Optional DB (HGNN) features
PG_DSN = os.getenv("SEEDCORE_PG_DSN", os.getenv("PG_DSN"))
PSYCOPG_OK = True
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception:
    PSYCOPG_OK = False

API_BASE = os.getenv("SEEDCORE_API", "http://127.0.0.1:8002")
API_V1_BASE = f"{API_BASE}/api/v1"


# ───────────────────────────── Helpers ─────────────────────────────

def _now():
    return datetime.now(timezone.utc)

def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso

def _parse_since(val: str | None):
    if not val:
        return None
    val = val.strip().lower()
    m = re.fullmatch(r"(\d+)([smhd])", val)
    if m:
        n, u = int(m.group(1)), m.group(2)
        delta = {"s": timedelta(seconds=n),
                 "m": timedelta(minutes=n),
                 "h": timedelta(hours=n),
                 "d": timedelta(days=n)}[u]
        return _now() - delta
    try:
        return datetime.fromisoformat(val).replace(tzinfo=timezone.utc)
    except Exception:
        return None

def _fuzzy(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()

def _http_get(path: str):
    r = requests.get(path, timeout=20)
    r.raise_for_status()
    return r.json()

def _http_post(path: str, payload: dict):
    r = requests.post(path, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()

def _db():
    if not (PG_DSN and PSYCOPG_OK):
        raise RuntimeError("DB features are unavailable (set PG_DSN and install psycopg2).")
    return psycopg2.connect(PG_DSN, cursor_factory=RealDictCursor)

def _print_soft_disable():
    if not PG_DSN:
        print("ℹ️ DB DSN not set (PG_DSN). Graph/HGNN commands disabled.")
    if not PSYCOPG_OK:
        print("ℹ️ psycopg2 not installed. Run: pip install psycopg2-binary")
        print("   This enables graph operations like 'graph stats', 'graph link', etc.")


# ───────────────────────────── HTTP: tasks/facts/health ─────────────────────────────

def api_health():
    try:
        j = _http_get(f"{API_BASE}/health")
        print(f"🏥 Health: {j.get('status','unknown')}  service={j.get('service')} version={j.get('version')}")
    except Exception as e:
        print(f"❌ Health check failed: {e}")

def api_readyz():
    try:
        j = _http_get(f"{API_BASE}/readyz")
        print(f"✅ Ready: {j.get('status','unknown')}")
        for k, v in (j.get("deps") or {}).items():
            print(f"  • {k}: {v}")
    except Exception as e:
        print(f"❌ Readiness failed: {e}")

def api_eventizer_test(text: str, task_type: str = "", domain: str = "", preserve_original: bool = False):
    """Test the eventizer service via /ops endpoint or task creation fallback."""
    try:
        # Try the new /ops/eventizer/process endpoint first
        ops_base = API_BASE.replace(":8002", ":8000")  # Ray Serve typically runs on 8000
        payload = {
            "text": text,
            "task_type": task_type,
            "domain": domain,
            "preserve_pii": preserve_original,
            "include_metadata": True
        }
        
        try:
            j = _http_post(f"{ops_base}/ops/eventizer/process", payload)
            print(f"🎯 Eventizer Result (via /ops):")
            print(f"  • Confidence: {j.get('confidence', {}).get('overall_confidence', 'N/A')}")
            print(f"  • Event Tags: {j.get('event_tags', {})}")
            print(f"  • Attributes: {j.get('attributes', {})}")
            print(f"  • Processing Time: {j.get('processing_time_ms', 'N/A')}ms")
            print(f"  • PII Redacted: {j.get('pii_redacted', False)}")
            if j.get('pii_redacted') and preserve_original:
                print(f"  • Original Text: {j.get('original_text', 'N/A')}")
                print(f"  • Processed Text: {j.get('processed_text', 'N/A')}")
        except Exception as ops_error:
            print(f"⚠️ /ops endpoint failed ({ops_error}), trying fallback...")
            # Fallback: create a task and check the enriched params
            task_payload = {
                "type": task_type or "query",  # Default to TaskType.QUERY
                "description": text,
                "domain": domain,
                "preserve_original_text": preserve_original,
                "params": {}
            }
            t = _http_post(f"{API_V1_BASE}/tasks", task_payload)
            enriched_params = t.get('params', {})
            if 'event_tags' in enriched_params:
                print(f"🎯 Eventizer Result (via task creation):")
                event_tags = enriched_params.get('event_tags', {})
                print(f"  • Confidence: {event_tags.get('confidence', 'N/A')}")
                print(f"  • Event Types: {event_tags.get('event_types', [])}")
                print(f"  • Needs ML Fallback: {event_tags.get('needs_ml_fallback', False)}")
                print(f"  • Processing Time: {enriched_params.get('eventizer_metadata', {}).get('processing_time_ms', 'N/A')}ms")
            else:
                print("❌ No eventizer results found in task params")
                
    except Exception as e:
        print(f"❌ Eventizer test failed: {e}")

def api_list_tasks(status=None, typ=None, since=None, limit=None):
    try:
        j = _http_get(f"{API_V1_BASE}/tasks")
    except Exception as e:
        print(f"❌ Could not list tasks: {e}")
        return
    items = j.get("items", [])
    since_dt = _parse_since(since)
    def _ok(t):
        s = (t.get("status") or "").lower()
        tt= (t.get("type") or "").lower()
        when = t.get("updated_at") or t.get("created_at")
        if status and not (s.startswith(status.lower()) or s == status.lower()):
            return False
        if typ and not (typ.lower() in tt or tt == typ.lower()):
            return False
        if since_dt:
            try:
                dt = datetime.fromisoformat(when)
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                if dt < since_dt: return False
            except Exception:
                pass
        return True
    items = [t for t in sorted(items, key=lambda x: x.get("created_at") or "", reverse=True) if _ok(t)]
    if limit: items = items[: int(limit)]
    print(f"📝 Tasks ({len(items)}/{j.get('total', len(items))})"
          f"{' | status='+status if status else ''}"
          f"{' | type='+typ if typ else ''}"
          f"{' | since='+since if since else ''}"
          f"{' | limit='+str(limit) if limit else ''}")
    for t in items:
        desc = (t.get("description") or "")[:60]
        print(f"  - {t['id'][:8]} [{t.get('type')}] {(t.get('status') or '').upper():<10} | {desc:<60} | Updated: {_fmt_dt(t.get('updated_at'))}")

def api_task_status(prefix: str):
    try:
        j = _http_get(f"{API_V1_BASE}/tasks")
        items = j.get("items", [])
        matches = [t for t in items if t["id"].startswith(prefix)]
        if not matches:
            print(f"❌ No task with prefix {prefix}")
            return
        if len(matches) > 1:
            print("⚠️ Multiple matches:")
            for t in matches:
                print(f"   {t['id']} [{t.get('type')}] {t.get('status')}")
            return
        tid = matches[0]["id"]
        t = _http_get(f"{API_V1_BASE}/tasks/{tid}")
        print(f"📊 {t['id']} [{t.get('type')}] {(t.get('status') or '').upper()}")
        print(f"   Drift: {t.get('drift_score')}  Updated: {_fmt_dt(t.get('updated_at'))}")
        if t.get("error"):  print(f"   🔴 {t['error']}")
        if t.get("result"): print(f"   ✅ {json.dumps(t['result'])[:200]}{'…' if len(json.dumps(t['result']))>200 else ''}")
    except Exception as e:
        print(f"❌ Status failed: {e}")

def api_search(q, status=None, typ=None, since=None, limit=None):
    try:
        j = _http_get(f"{API_V1_BASE}/tasks")
    except Exception as e:
        print(f"❌ Could not search tasks: {e}")
        return
    since_dt = _parse_since(since)
    scored = []
    for t in j.get("items", []):
        fields = [t.get("id",""), t.get("type",""), t.get("description",""), json.dumps(t.get("result")) if t.get("result") else ""]
        score = max((_fuzzy(f, q) for f in fields if f), default=0.0)
        if score >= 0.45: scored.append((score, t))
    scored.sort(key=lambda s: (s[1].get("created_at") or "", s[0]), reverse=True)
    def _ok(t):
        s = (t.get("status") or "").lower()
        tt= (t.get("type") or "").lower()
        when = t.get("updated_at") or t.get("created_at")
        if status and not (s.startswith(status.lower()) or s == status.lower()):
            return False
        if typ and not (typ.lower() in tt or tt == typ.lower()):
            return False
        if since_dt:
            try:
                dt = datetime.fromisoformat(when)
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                if dt < since_dt: return False
            except Exception:
                pass
        return True
    items = [t for _, t in scored if _ok(t)]
    if limit: items = items[: int(limit)]
    if not items:
        print(f"🔍 No matches for '{q}'")
        return
    print(f"🔍 Matches for '{q}' ({len(items)})")
    for t in items:
        print(f"  - {t['id'][:8]} [{t.get('type')}] {(t.get('status') or '').upper():<10} | {(t.get('description') or '')[:60]}")

def api_ask_interactive_disambiguation(prompt: str):
    """Interactive disambiguation for vague prompts by querying existing artifacts"""
    try:
        # Query for existing artifacts that might match the prompt
        j = _http_get(f"{API_V1_BASE}/facts")
        artifacts = []
        for f in j.get("items", []):
            if "artifact" in f.get("text", "").lower() or "report" in f.get("text", "").lower():
                artifacts.append(f)
        
        if not artifacts:
            return None  # No artifacts found, proceed with normal flow
        
        print(f"\n🤔 That's a bit vague. I found {len(artifacts)} existing artifacts. Which one do you mean?")
        for i, artifact in enumerate(artifacts[:5], 1):  # Show max 5 options
            text = artifact.get("text", "")[:60]
            print(f"[{i}] {artifact['id'][:8]}: {text}")
        print(f"[{len(artifacts)+1}] None of the above - create a new task.")
        
        try:
            choice = input("\nEnter number: ").strip()
            choice_num = int(choice)
            if 1 <= choice_num <= len(artifacts):
                selected = artifacts[choice_num - 1]
                print(f"🚀 Creating task to work with artifact {selected['id'][:8]}...")
                return selected
            elif choice_num == len(artifacts) + 1:
                print("🚀 Creating new task...")
                return None
            else:
                print("❌ Invalid choice, creating new task...")
                return None
        except (ValueError, KeyboardInterrupt):
            print("\n❌ Invalid input, creating new task...")
            return None
    except Exception as e:
        print(f"ℹ️ Could not query artifacts: {e}")
        return None

def api_ask(prompt: str, agent_id: str | None = None, organ_id: str | None = None, no_disambiguation: bool = False):
    # Check for vague prompts that might benefit from disambiguation
    vague_keywords = ["get", "latest", "report", "document", "file", "data"]
    is_vague = not no_disambiguation and any(keyword in prompt.lower() for keyword in vague_keywords) and len(prompt.split()) <= 4
    
    # If agent or organ is provided, we create a more specific graph task
    if agent_id or organ_id:
        print("🧠 Graph-aware task creation...")
        # For now, we'll create a regular task but with enhanced context
        # In a full implementation, this would call a new API endpoint
        # that uses create_graph_rag_task with agent/organ parameters
        payload = {
            "description": prompt,
            "type": "graph",  # TaskType.GRAPH
            "drift_score": 0.1,  # Lower drift for graph-aware tasks
            "run_immediately": True,
            "params": {
                "prompt": prompt,
                "agent_id": agent_id,
                "organ_id": organ_id
            }
        }
        t = _http_post(f"{API_V1_BASE}/tasks", payload)
        print(f"🚀 Graph Task {t['id'][:8]} [{t['type']}] → {t['status']}")
        if agent_id:
            print(f"   📋 Assigned to agent: {agent_id}")
        if organ_id:
            print(f"   🏢 Executed by organ: {organ_id}")
    else:
        # Check for interactive disambiguation for vague prompts
        if is_vague:
            selected_artifact = api_ask_interactive_disambiguation(prompt)
            if selected_artifact:
                # Create task with artifact context
                enhanced_prompt = f"{prompt} (working with artifact: {selected_artifact['text'][:100]})"
                payload = {
                    "description": enhanced_prompt,
                    "type": "query",  # TaskType.QUERY
                    "drift_score": 0.3,
                    "run_immediately": True,
                    "params": {
                        "original_prompt": prompt,
                        "artifact_id": selected_artifact['id'],
                        "artifact_text": selected_artifact['text']
                    }
                }
                t = _http_post(f"{API_V1_BASE}/tasks", payload)
                print(f"🚀 Artifact Task {t['id'][:8]} [{t['type']}] → {t['status']}")
                return
        
        # Original fuzzy logic for general queries
        payload = {"description": prompt, "type": "query", "drift_score": 0.9, "run_immediately": True, "params": {}}  # TaskType.QUERY
        p = prompt.lower()
        if "plan" in p:
            payload["type"] = "query";   payload["drift_score"] = 0.1  # TaskType.QUERY
        elif "analyze" in p or "reason" in p:
            payload["type"] = "query"; payload["drift_score"] = 0.2  # TaskType.QUERY
        t = _http_post(f"{API_V1_BASE}/tasks", payload)
        print(f"🚀 Task {t['id'][:8]} [{t['type']}] → {t['status']}")

def api_facts_list():
    try:
        j = _http_get(f"{API_V1_BASE}/facts")
        items = j.get("items", [])
        if not items:
            print("📭 No facts")
            return
        print(f"📖 Facts ({len(items)}):")
        for f in items:
            print(f"  - {f['id'][:8]}: {f['text']}")
    except Exception as e:
        print(f"❌ facts failed: {e}")

def api_fact_add(text: str):
    j = _http_post(f"{API_V1_BASE}/facts", {"text": text, "metadata": {"source": "cli"}})
    print(f"✨ Fact {j['id'][:8]} created")

def api_fact_del(fid: str):
    r = requests.delete(f"{API_V1_BASE}/facts/{fid}", timeout=20)
    if r.status_code == 404:
        print("❌ Not found")
    else:
        r.raise_for_status(); print("🗑️ Deleted")


# ───────────────────────────── DB: HGNN graph ops ─────────────────────────────

def db_stats():
    try:
        with _db() as con, con.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM graph_node_map"); n_nodes = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM hgnn_edges");     n_edges = cur.fetchone()["n"]
            print(f"🧠 HGNN: {n_nodes} nodes, {n_edges} edges (graph_node_map / hgnn_edges)")
    except Exception as e:
        print(f"❌ DB stats failed: {e}")

def db_edges(node_id: int, direction="both", limit=50):
    q = {
        "both": "SELECT * FROM hgnn_edges WHERE src_node_id=%s OR dst_node_id=%s LIMIT %s",
        "out":  "SELECT * FROM hgnn_edges WHERE src_node_id=%s LIMIT %s",
        "in":   "SELECT * FROM hgnn_edges WHERE dst_node_id=%s LIMIT %s",
    }[direction]
    try:
        with _db() as con, con.cursor() as cur:
            if direction == "both":
                cur.execute(q, (node_id, node_id, limit))
            else:
                cur.execute(q, (node_id, limit))
            rows = cur.fetchall()
            if not rows:
                print("Ø no edges")
                return
            for r in rows:
                print(f"  {r['src_node_id']} -> {r['dst_node_id']}  [{r['edge_type']}]")
    except Exception as e:
        print(f"❌ edges failed: {e}")

# ensure_* helpers (idempotent)
def db_ensure(kind: str, name: str):
    fn = {
        "agent":"ensure_agent_node",
        "organ":"ensure_organ_node",
        "model":"ensure_model_node",
        "service":"ensure_service_node",
        "skill":"ensure_skill_node",
        "policy":"ensure_policy_node",
    }.get(kind)
    if not fn:
        print("❌ kind must be one of: agent, organ, model, service, skill, policy")
        return
    try:
        with _db() as con, con.cursor() as cur:
            cur.execute(f"SELECT {fn}(%s) AS node_id", (name,))
            nid = cur.fetchone()["node_id"]
            print(f"✅ ensured {kind}='{name}' node_id={nid}")
    except Exception as e:
        print(f"❌ ensure {kind} failed: {e}")

def db_link(rel: str, *args: str):
    # map to edge tables
    try:
        with _db() as con, con.cursor() as cur:
            if rel == "member_of":  # agent member_of organ
                agent_id, organ_id = args
                cur.execute("""
                  INSERT INTO agent_member_of_organ(agent_id, organ_id)
                  VALUES (%s,%s) ON CONFLICT DO NOTHING
                """, (agent_id, organ_id))
                print(f"🔗 Linked agent '{agent_id}' as member_of organ '{organ_id}'")
            elif rel == "collab":    # agent collab agent
                src_agent, dst_agent = args
                cur.execute("""
                  INSERT INTO agent_collab_agent(src_agent, dst_agent)
                  VALUES (%s,%s) ON CONFLICT DO NOTHING
                """, (src_agent, dst_agent))
                print(f"🔗 Linked agent '{src_agent}' collaborates with agent '{dst_agent}'")
            elif rel == "provides":  # organ provides skill
                organ_id, skill_name = args
                cur.execute("""
                  INSERT INTO organ_provides_skill(organ_id, skill_name)
                  VALUES (%s,%s) ON CONFLICT DO NOTHING
                """, (organ_id, skill_name))
                print(f"🔗 Linked organ '{organ_id}' provides skill '{skill_name}'")
            elif rel == "uses-service":  # organ uses service
                organ_id, service_name = args
                cur.execute("""
                  INSERT INTO organ_uses_service(organ_id, service_name)
                  VALUES (%s,%s) ON CONFLICT DO NOTHING
                """, (organ_id, service_name))
                print(f"🔗 Linked organ '{organ_id}' uses service '{service_name}'")
            elif rel == "uses-model":    # agent uses model
                agent_id, model_name = args
                cur.execute("""
                  INSERT INTO agent_uses_model(agent_id, model_name)
                  VALUES (%s,%s) ON CONFLICT DO NOTHING
                """, (agent_id, model_name))
                print(f"🔗 Linked agent '{agent_id}' uses model '{model_name}'")
            elif rel == "governed_by":   # organ governed_by policy
                organ_id, policy_name = args
                cur.execute("""
                  INSERT INTO organ_governed_by_policy(organ_id, policy_name)
                  VALUES (%s,%s) ON CONFLICT DO NOTHING
                """, (organ_id, policy_name))
                print(f"🔗 Linked organ '{organ_id}' governed_by policy '{policy_name}'")
            else:
                print("❌ rel must be one of: member_of, collab, provides, uses-service, uses-model, governed_by")
                return
            con.commit()
    except psycopg2.errors.ForeignKeyViolation as e:
        print(f"❌ Link failed: A node does not exist.")
        print(f"   Ensure both '{args[0]}' and '{args[1]}' were created with 'graph ensure' first.")
    except psycopg2.errors.UniqueViolation as e:
        print(f"ℹ️ Link already exists (skipped)")
    except Exception as e:
        print(f"❌ link {rel} failed: {e}")

def db_create_graph_task_v2(kind: str, start_csv: str, k: int, desc: str, agent_id: str|None, organ_id: str|None, topk: int|None):
    # kind in {embed, rag}
    arr = [int(x) for x in start_csv.split(",") if x.strip()]
    if not arr:
        print("❌ provide --start as CSV of integers")
        return
    try:
        with _db() as con, con.cursor() as cur:
            if kind == "embed":
                cur.execute("""
                  SELECT create_graph_embed_task(%s,%s,%s,%s,%s) AS id
                """, (arr, k, desc, agent_id, organ_id))
            elif kind == "rag":
                topk = topk or 10
                cur.execute("""
                  SELECT create_graph_rag_task(%s,%s,%s,%s,%s,%s) AS id
                """, (arr, k, topk, desc, agent_id, organ_id))
            else:
                print("❌ kind must be 'embed' or 'rag'")
                return
            tid = cur.fetchone()["id"]
            con.commit()
            print(f"🚀 created task {tid} (with cross-layer wiring)")
    except Exception as e:
        print(f"❌ create_graph_{kind}_task failed: {e}")


# ───────────────────────────── CLI ─────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        description="🎯 SeedCore CLI — unified surface for tasks, facts, and HGNN graph",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", metavar="command")

    # ─── Health / Readiness ───
    sub.add_parser("health", help="Check API health (status, service, version)")
    sub.add_parser("readyz", help="Check API readiness (DB + deps)")
    
    # Eventizer testing
    et = sub.add_parser("eventizer", help="Test eventizer service with sample text")
    et.add_argument("text", help="Text to process through eventizer")
    et.add_argument("--type", help="Task type (default: 'test')")
    et.add_argument("--domain", help="Domain context")
    et.add_argument("--preserve-original", action="store_true", help="Preserve original text (for PII testing)")

    # ─── Tasks / Facts ───
    tp = sub.add_parser("tasks", help="List tasks with optional filters")
    tp.add_argument("--status", help="Filter by status (queued, running, completed, failed)")
    tp.add_argument("--type", help="Filter by task type (chat, query, action, graph, maintenance, unknown)")
    tp.add_argument("--since", help="Filter by updated time (e.g., 1h, 24h, 2d, 2024-01-01)")
    tp.add_argument("--limit", type=int, help="Limit number of tasks shown")

    sp = sub.add_parser("search", help="Fuzzy search tasks across id/type/description/result")
    sp.add_argument("query", help="Search query string")
    sp.add_argument("--status", help="Filter by status")
    sp.add_argument("--type", help="Filter by task type")
    sp.add_argument("--since", help="Filter by updated time")
    sp.add_argument("--limit", type=int, help="Limit results")

    st = sub.add_parser("status", help="Quick task status by ID prefix")
    st.add_argument("prefix", help="Task ID prefix (short form accepted)")

    ts = sub.add_parser("taskstatus", help="Detailed task status by ID prefix")
    ts.add_argument("prefix", help="Task ID prefix")

    ap = sub.add_parser("ask", help="Create and run a task from natural language prompt")
    ap.add_argument("prompt", nargs=argparse.REMAINDER, help="Prompt string")
    ap.add_argument("--agent", help="Agent ID to own this task")
    ap.add_argument("--organ", help="Organ ID to execute this task")
    ap.add_argument("--no-disambiguation", action="store_true", help="Disable interactive disambiguation for vague prompts")

    sub.add_parser("facts", help="List all facts")
    gf = sub.add_parser("genfact", help="Create a new fact")
    gf.add_argument("text", nargs=argparse.REMAINDER, help="Fact text")
    df = sub.add_parser("delfact", help="Delete a fact by ID")
    df.add_argument("id", help="Fact ID")

    # ─── Graph / HGNN ───
    gp = sub.add_parser("graph", help="Graph/HGNN operations (requires PG_DSN)")
    gsub = gp.add_subparsers(dest="gcmd", metavar="graph-command")

    gsub.add_parser("stats", help="Show node and edge counts in HGNN")
    ge = gsub.add_parser("edges", help="Show edges for a node")
    ge.add_argument("node_id", type=int, help="Source or destination node ID")
    ge.add_argument("--dir", choices=["both", "out", "in"], default="both", help="Direction (default=both)")
    ge.add_argument("--limit", type=int, default=50, help="Limit edges shown")

    geu = gsub.add_parser("ensure", help="Ensure a node exists (agent, organ, model, service, skill, policy)")
    geu.add_argument("kind", choices=["agent", "organ", "model", "service", "skill", "policy"])
    geu.add_argument("name", help="External ID or name")

    gl = gsub.add_parser("link", help="Create graph relation between nodes")
    gl.add_argument("rel", choices=["member_of", "collab", "provides", "uses-service", "uses-model", "governed_by"])
    gl.add_argument("a", help="First argument (varies by relation)")
    gl.add_argument("b", help="Second argument (varies by relation)")

    gct = gsub.add_parser("create-task", help="Create graph embed/rag task (cross-layer wiring)")
    gct.add_argument("kind", choices=["embed", "rag"], help="Task kind")
    gct.add_argument("--start", required=True, help="CSV of start node IDs")
    gct.add_argument("--k", type=int, default=2, help="Hop count (default=2)")
    gct.add_argument("--topk", type=int, help="Top-K results (rag only)")
    gct.add_argument("--desc", default="", help="Task description")
    gct.add_argument("--agent", help="Agent ID for cross-layer wiring")
    gct.add_argument("--organ", help="Organ ID for cross-layer wiring")

    # Extended epilog with examples
    p.epilog = """\
Examples:
  ./seedcore_cli.py health                    # Check SeedCore API health
  ./seedcore_cli.py readyz                    # Check SeedCore API readiness
  ./seedcore_cli.py eventizer "Emergency in building A" --type security --domain physical
  ./seedcore_cli.py tasks --status running --limit 5
  ./seedcore_cli.py search tea --status completed
  ./seedcore_cli.py ask analyze the incident 12345
  ./seedcore_cli.py ask "get the latest report" --agent "sec-analyst-01" --organ "cyber-defense"
  ./seedcore_cli.py facts
  ./seedcore_cli.py genfact "Mars mission launch window"
  ./seedcore_cli.py delfact 7f9a
  ./seedcore_cli.py graph stats
  ./seedcore_cli.py graph edges 42 --dir out --limit 10
  ./seedcore_cli.py graph ensure agent "agent-uuid-123"
  ./seedcore_cli.py graph link member_of 101 201
  ./seedcore_cli.py graph create-task embed --start 1,2,3 --k 2 --desc "embedding test"
"""
    return p

def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "health":
        api_health(); return
    if args.cmd == "readyz":
        api_readyz(); return
    if args.cmd == "eventizer":
        api_eventizer_test(args.text, args.type, args.domain, args.preserve_original); return

    if args.cmd == "tasks":
        api_list_tasks(args.status, args.type, args.since, args.limit); return
    if args.cmd == "search":
        api_search(args.query, args.status, args.type, args.since, args.limit); return
    if args.cmd == "status" or args.cmd == "taskstatus":
        api_task_status(args.prefix); return
    if args.cmd == "ask":
        prompt = " ".join(args.prompt).strip()
        if not prompt:
            print("❌ provide a prompt"); return
        api_ask(prompt, args.agent, args.organ, args.no_disambiguation); return

    if args.cmd == "facts":
        api_facts_list(); return
    if args.cmd == "genfact":
        text = " ".join(args.text).strip()
        if not text: print("❌ provide text"); return
        api_fact_add(text); return
    if args.cmd == "delfact":
        api_fact_del(args.id); return

    # Graph/DB section
    if args.cmd == "graph":
        if not (PG_DSN and PSYCOPG_OK):
            _print_soft_disable(); return
        if args.gcmd == "stats":
            db_stats(); return
        if args.gcmd == "edges":
            db_edges(args.node_id, args.dir, args.limit); return
        if args.gcmd == "ensure":
            db_ensure(args.kind, args.name); return
        if args.gcmd == "link":
            db_link(args.rel, args.a, args.b); return
        if args.gcmd == "create-task":
            db_create_graph_task_v2(args.kind, args.start, args.k, args.desc, args.agent, args.organ, args.topk); return
        print("ℹ️ graph subcommands: stats | edges | ensure | link | create-task"); return

    parser.print_help()

if __name__ == "__main__":
    main()

