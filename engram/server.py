"""Engram HTTP server — keeps Engram alive as a long-running daemon.

Exposes REST API for memory operations and serves the dashboard.
"""

import json
import threading
import time
from collections import defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from typing import Optional

from .core import Engram


class _Handler(BaseHTTPRequestHandler):
    """HTTP request handler for Engram server."""

    # Set by EngramServer before starting
    engram: Engram = None
    dashboard_html: str = ""

    # Metrics tracking: query log + aggregate stats
    _metrics_lock = threading.Lock()
    _metrics_queries: list = []  # list of {ts, query, count, top_score, categories}
    _metrics_max_queries = 500   # rolling window

    @classmethod
    def _log_query(cls, query: str, count: int, top_score: float, categories: list):
        with cls._metrics_lock:
            cls._metrics_queries.append({
                "ts": time.time(),
                "query": query[:200],
                "count": count,
                "top_score": round(top_score, 3) if top_score else 0,
                "categories": categories[:5],
            })
            if len(cls._metrics_queries) > cls._metrics_max_queries:
                cls._metrics_queries = cls._metrics_queries[-cls._metrics_max_queries:]

    @classmethod
    def _get_metrics(cls) -> dict:
        with cls._metrics_lock:
            qs = list(cls._metrics_queries)
        if not qs:
            return {
                "total_queries": 0, "hit_rate": 0, "hits": 0, "misses": 0,
                "avg_score": 0, "min_score": 0, "max_score": 0, "median_score": 0,
                "category_distribution": {}, "recent_queries": [],
            }

        total = len(qs)
        hits = sum(1 for q in qs if q["count"] > 0)
        avg_score = sum(q["top_score"] for q in qs) / total if total else 0
        scores = [q["top_score"] for q in qs]
        scores.sort()

        # Category distribution
        cat_counts = defaultdict(int)
        for q in qs:
            for c in q["categories"]:
                cat_counts[c] += 1

        # Recent queries (last 20)
        recent = qs[-20:]

        return {
            "total_queries": total,
            "hit_rate": round(hits / total, 3) if total else 0,
            "hits": hits,
            "misses": total - hits,
            "avg_score": round(avg_score, 3),
            "min_score": round(scores[0], 3),
            "max_score": round(scores[-1], 3),
            "median_score": round(scores[len(scores)//2], 3),
            "category_distribution": dict(cat_counts),
            "recent_queries": list(reversed(recent)),
        }

    def log_message(self, format, *args):
        """Suppress default logging to stderr."""
        pass

    def _json(self, data, status=200):
        """Send JSON response."""
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        """Read JSON body from request."""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            stats = self.engram.stats()
            self._json({
                "status": "ok",
                "layers": {
                    "1": "hot_cache",
                    "2": "semantic_index",
                },
                "total_memories": stats["semantic_index"]["total_memories"],
                "uptime_seconds": 0,  # placeholder
            })

        elif path.startswith("/assets/"):
            # Serve React build assets
            import os as _os_assets
            dist_dir = _os_assets.path.join(_os_assets.path.dirname(__file__), '..', 'dashboard', 'dist')
            asset_path = _os_assets.path.join(dist_dir, path.lstrip('/'))
            if _os_assets.path.isfile(asset_path):
                with open(asset_path, 'rb') as f:
                    body = f.read()
                ct = 'text/css' if asset_path.endswith('.css') else 'application/javascript'
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"error": "not found"}, status=404)

        elif path == "/stats":
            self._json(self.engram.stats())

        elif path == "/layers":
            stats = self.engram.stats()
            self._json({
                "layers": [
                    {"id": 1, "name": "Hot Cache", "items": stats["hot_cache_size"]},
                    {"id": 2, "name": "Semantic Index", "items": stats["semantic_index"]["total_memories"],
                     "categories": stats["semantic_index"]["categories"]},
                ]
            })

        elif path == "/metrics":
            self._json(self._get_metrics())

        elif path == "/dashboard" or path == "/":
            body = self.dashboard_html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            # Try serving from dashboard dist (favicon, icons, etc.)
            import os as _os_static
            dist_dir = _os_static.path.join(_os_static.path.dirname(__file__), '..', 'dashboard', 'dist')
            asset_path = _os_static.path.join(dist_dir, path.lstrip('/'))
            if _os_static.path.isfile(asset_path):
                with open(asset_path, 'rb') as f:
                    body = f.read()
                ct = 'image/svg+xml' if asset_path.endswith('.svg') else 'application/octet-stream'
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"error": "not found"}, status=404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/remember":
            data = self._read_json()
            memory_id = self.engram.remember(
                content=data.get("content", ""),
                layer=data.get("layer", 2),
                category=data.get("category", "general"),
                importance=data.get("importance", 0.5),
                metadata=data.get("metadata"),
            )
            self._json({"status": "stored", "memory_id": memory_id})

        elif path == "/recall":
            data = self._read_json()
            result = self.engram.recall(
                query=data.get("query", ""),
                layers=data.get("layers"),
                limit=data.get("limit", 10),
                min_score=data.get("min_score", 0.5),
            )
            hits = result.semantic_hits
            # Auto-log metrics
            self._log_query(
                query=data.get("query", ""),
                count=len(hits),
                top_score=hits[0].score if hits else 0,
                categories=[h.memory.category for h in hits],
            )
            self._json({
                "query": data.get("query", ""),
                "count": len(hits),
                "hot_cache": result.hot_cache,
                "semantic_hits": [
                    {"content": h.memory.content, "score": h.score, "category": h.memory.category}
                    for h in hits
                ],
            })

        elif path == "/forget":
            data = self._read_json()
            ok = self.engram.forget(data.get("memory_id", ""))
            self._json({"status": "deleted" if ok else "not_found"})

        # ── Skills endpoints (Layer 3: Procedural Memory) ──

        elif path == "/skills/search":
            data = self._read_json()
            result = self.engram.recall(
                query=data.get("query", ""),
                layers=data.get("layers"),
                limit=data.get("limit", 5),
                min_score=data.get("min_score", 0.2),
            )
            # Filter to only skill-category memories
            skill_hits = [
                {"name": h.memory.metadata.get("skill_name", "") if h.memory.metadata else "",
                 "description": h.memory.content,
                 "score": h.score,
                 "category": h.memory.metadata.get("skill_category", "") if h.memory.metadata else ""}
                for h in result.semantic_hits
                if h.memory.category == "skill"
            ]
            self._json({
                "query": data.get("query", ""),
                "count": len(skill_hits),
                "skills": skill_hits,
            })

        elif path == "/skills/index":
            # Index all skills from disk into Engram
            import os as _os4
            skills_dir = _os4.path.join(_os4.path.dirname(_os4.path.abspath(__file__)), "..", "..", ".hermes", "skills")
            # Also check F: drive path
            alt_dir = "F:/hermes/.hermes/skills"
            indexed = 0
            for base in [skills_dir, alt_dir]:
                if _os4.path.isdir(base):
                    for root, dirs, files in _os4.walk(base):
                        for f in files:
                            if f == "SKILL.md":
                                skill_path = _os4.path.join(root, f)
                                skill_name = _os4.path.basename(root)
                                try:
                                    with open(skill_path, encoding="utf-8") as sf:
                                        content = sf.read()
                                    # Extract description (first paragraph after frontmatter)
                                    desc = content
                                    if content.startswith("---"):
                                        parts = content.split("---", 2)
                                        if len(parts) >= 3:
                                            desc = parts[2].strip().split("\n\n")[0][:500]
                                    self.engram.remember(
                                        content=desc,
                                        layer=2,
                                        category="skill",
                                        importance=0.7,
                                        metadata={
                                            "skill_name": skill_name,
                                            "skill_path": skill_path,
                                            "skill_category": _os4.path.basename(_os4.path.dirname(root)),
                                        },
                                    )
                                    indexed += 1
                                except Exception:
                                    pass
            self._json({"status": "indexed", "count": indexed})

        elif path == "/skills/list" or path == "/skills/list/":
            # List skills via semantic layer directly  
            import traceback as _tb
            skills = []
            error_msg = None
            try:
                results = self.engram._semantic.recall(
                    query="skills",
                    limit=200,
                    min_score=0.0,
                    category_filter="skill",
                )
                seen = set()
                for r in results:
                    name = r.memory.metadata.get("skill_name", "") if r.memory.metadata else ""
                    if name and name not in seen:
                        seen.add(name)
                        skills.append({
                            "name": name,
                            "description": r.memory.content[:200] if r.memory.content else "",
                            "category": r.memory.metadata.get("skill_category", "") if r.memory.metadata else "",
                            "score": round(r.score, 3),
                        })
                error_msg = f"raw results: {len(results)}, filtered: {len(skills)}"
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
            self._json({"skills": skills, "count": len(skills), "error": error_msg})

        # ── Layer 3: Procedural Memory (workflows) ──

        elif path == "/procedures/remember":
            data = self._read_json()
            memory_id = self.engram._semantic.remember(
                content=data.get("content", ""),
                category="layer3_procedural",
                importance=data.get("importance", 0.7),
                metadata={
                    "name": data.get("name", ""),
                    "steps": data.get("steps", ""),
                    "source_session": data.get("source_session", ""),
                    "domain": data.get("domain", ""),
                    "created_at": data.get("created_at", ""),
                },
            )
            self._json({"status": "stored", "memory_id": memory_id, "layer": 3})

        elif path == "/procedures/search":
            data = self._read_json()
            results = self.engram._semantic.recall(
                query=data.get("query", ""),
                limit=data.get("limit", 20),
                min_score=data.get("min_score", 0.2),
                category_filter="layer3_procedural",
            )
            hits = [{
                "name": r.memory.metadata.get("name", ""),
                "content": r.memory.content[:300],
                "steps": r.memory.metadata.get("steps", ""),
                "domain": r.memory.metadata.get("domain", ""),
                "score": round(r.score, 3),
            } for r in results]
            self._json({"query": data.get("query", ""), "count": len(hits), "procedures": hits})

        elif path == "/procedures/list":
            results = self.engram._semantic.recall(
                query="workflow procedure process",
                limit=200, min_score=0.0,
                category_filter="layer3_procedural",
            )
            seen = set()
            items = []
            for r in results:
                name = r.memory.metadata.get("name", "") if r.memory.metadata else ""
                if name and name not in seen:
                    seen.add(name)
                    items.append({
                        "name": name,
                        "content": r.memory.content[:200],
                        "domain": r.memory.metadata.get("domain", "") if r.memory.metadata else "",
                        "score": round(r.score, 3),
                    })
            self._json({"procedures": items, "count": len(items)})

        # ── Layer 4: Episodic Memory (sessions/events) ──

        elif path == "/episodes/remember":
            data = self._read_json()
            memory_id = self.engram._semantic.remember(
                content=data.get("content", ""),
                category="layer4_episodic",
                importance=data.get("importance", 0.6),
                metadata={
                    "title": data.get("title", ""),
                    "session_id": data.get("session_id", ""),
                    "timestamp": data.get("timestamp", ""),
                    "tags": ",".join(data.get("tags", [])),
                    "outcome": data.get("outcome", ""),
                },
            )
            self._json({"status": "stored", "memory_id": memory_id, "layer": 4})

        elif path == "/episodes/search":
            data = self._read_json()
            results = self.engram._semantic.recall(
                query=data.get("query", ""),
                limit=data.get("limit", 20),
                min_score=data.get("min_score", 0.2),
                category_filter="layer4_episodic",
            )
            hits = [{
                "title": r.memory.metadata.get("title", ""),
                "content": r.memory.content[:300],
                "session_id": r.memory.metadata.get("session_id", ""),
                "timestamp": r.memory.metadata.get("timestamp", ""),
                "tags": r.memory.metadata.get("tags", ""),
                "outcome": r.memory.metadata.get("outcome", ""),
                "score": round(r.score, 3),
            } for r in results]
            self._json({"query": data.get("query", ""), "count": len(hits), "episodes": hits})

        elif path == "/episodes/list":
            results = self.engram._semantic.recall(
                query="session conversation episode event",
                limit=200, min_score=0.0,
                category_filter="layer4_episodic",
            )
            seen = set()
            items = []
            for r in results:
                title = r.memory.metadata.get("title", "") if r.memory.metadata else ""
                if title and title not in seen:
                    seen.add(title)
                    items.append({
                        "title": title,
                        "content": r.memory.content[:200],
                        "timestamp": r.memory.metadata.get("timestamp", "") if r.memory.metadata else "",
                        "tags": r.memory.metadata.get("tags", "") if r.memory.metadata else "",
                        "outcome": r.memory.metadata.get("outcome", "") if r.memory.metadata else "",
                        "score": round(r.score, 3),
                    })
            self._json({"episodes": items, "count": len(items)})

        # ── Layer 5: Meta/Reflective Memory ──

        elif path == "/reflect":
            data = self._read_json()
            memory_id = self.engram._semantic.remember(
                content=data.get("content", ""),
                category="layer5_reflection",
                importance=data.get("importance", 0.8),
                metadata={
                    "topic": data.get("topic", ""),
                    "insight": data.get("insight", ""),
                    "action": data.get("action", ""),
                    "success": str(data.get("success", True)),
                    "timestamp": data.get("timestamp", ""),
                },
            )
            self._json({"status": "stored", "memory_id": memory_id, "layer": 5})

        elif path == "/reflections/search":
            data = self._read_json()
            results = self.engram._semantic.recall(
                query=data.get("query", ""),
                limit=data.get("limit", 20),
                min_score=data.get("min_score", 0.2),
                category_filter="layer5_reflection",
            )
            hits = [{
                "topic": r.memory.metadata.get("topic", ""),
                "content": r.memory.content[:300],
                "insight": r.memory.metadata.get("insight", ""),
                "action": r.memory.metadata.get("action", ""),
                "success": r.memory.metadata.get("success", ""),
                "score": round(r.score, 3),
            } for r in results]
            self._json({"query": data.get("query", ""), "count": len(hits), "reflections": hits})

        elif path == "/reflections/list":
            results = self.engram._semantic.recall(
                query="reflection insight improvement learn",
                limit=200, min_score=0.0,
                category_filter="layer5_reflection",
            )
            seen = set()
            items = []
            for r in results:
                topic = r.memory.metadata.get("topic", "") if r.memory.metadata else ""
                if topic and topic not in seen:
                    seen.add(topic)
                    items.append({
                        "topic": topic,
                        "content": r.memory.content[:200],
                        "insight": r.memory.metadata.get("insight", "") if r.memory.metadata else "",
                        "action": r.memory.metadata.get("action", "") if r.memory.metadata else "",
                        "success": r.memory.metadata.get("success", "") if r.memory.metadata else "",
                        "score": round(r.score, 3),
                    })
            self._json({"reflections": items, "count": len(items)})

        elif path == "/metrics/log":
            data = self._read_json()
            self._log_query(
                query=data.get("query", ""),
                count=data.get("count", 0),
                top_score=data.get("top_score", 0),
                categories=data.get("categories", []),
            )
            self._json({"status": "logged"})

        else:
            self._json({"error": "not found"}, status=404)


class EngramServer:
    """HTTP server wrapping Engram for long-running operation.

    Usage:
        server = EngramServer()
        server.start()  # blocks until stop() called from another thread
    """

    def __init__(
        self,
        persist_dir: str = "~/.hermes/engram",
        host: str = "127.0.0.1",
        port: int = 8092,
        auto_bootstrap: bool = True,
        budget_max_chars: int = 2000,
    ):
        self.persist_dir = persist_dir
        self.host = host
        self.port = port
        self._httpd: Optional[HTTPServer] = None
        self._engram: Optional[Engram] = None

        # Create the Engram instance (keeps ChromaDB open)
        self._engram = Engram(
            persist_dir=persist_dir,
            budget_max_chars=budget_max_chars,
            auto_bootstrap=auto_bootstrap,
        )

        # Pre-warm the embedding model so first request is fast
        self._engram._semantic.embedding_model.embed_single("warmup")

        # Default dashboard HTML
        self.dashboard_html = self._build_dashboard()

    @property
    def engram(self) -> Engram:
        return self._engram

    def start(self):
        """Start the HTTP server. Blocks until stop() is called."""
        # Configure handler class
        _Handler.engram = self._engram
        _Handler.dashboard_html = self.dashboard_html

        self._httpd = HTTPServer((self.host, self.port), _Handler)

        # If port=0, read the assigned port
        if self.port == 0:
            self.port = self._httpd.server_address[1]

        try:
            self._httpd.serve_forever()
        except KeyboardInterrupt:
            pass

    def stop(self):
        """Stop the HTTP server and release resources."""
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._engram:
            self._engram.close()
            self._engram = None

    def _build_dashboard(self) -> str:
        """Load React dashboard HTML from build output."""
        import os
        # Try React build first
        dist_dir = os.path.join(os.path.dirname(__file__), '..', 'dashboard', 'dist')
        html_path = os.path.join(dist_dir, 'index.html')
        if os.path.exists(html_path):
            with open(html_path) as f:
                return f.read()
        # Fallback: old dashboard.html
        html_path = os.path.join(os.path.dirname(__file__), 'dashboard.html')
        if os.path.exists(html_path):
            with open(html_path) as f:
                return f.read()
        return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Engram Dashboard</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #c9d1d9;
  --muted: #8b949e;
  --accent: #58a6ff;
  --green: #3fb950;
  --orange: #d2991d;
  --font-scale: 1.25;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: calc(14px * var(--font-scale));
  padding: calc(20px * var(--font-scale));
}
h1 { font-size: calc(24px * var(--font-scale)); margin-bottom: calc(16px * var(--font-scale)); }
.tabs { display: flex; gap: calc(4px * var(--font-scale)); margin-bottom: calc(16px * var(--font-scale)); border-bottom: 1px solid var(--border); }
.tab { padding: calc(8px * var(--font-scale)) calc(16px * var(--font-scale)); cursor: pointer; border: none; background: none; color: var(--muted); font-size: inherit; }
.tab.active { color: var(--accent); border-bottom: 2px solid var(--accent); }
.panel { display: none; }
.panel.active { display: block; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: calc(6px * var(--font-scale)); padding: calc(16px * var(--font-scale)); margin-bottom: calc(12px * var(--font-scale)); }
.stat { display: flex; justify-content: space-between; padding: calc(4px * var(--font-scale)) 0; border-bottom: 1px solid var(--border); }
.stat:last-child { border-bottom: none; }
.stat-label { color: var(--muted); }
.stat-value { font-weight: 600; }
.badge { background: var(--accent); color: var(--bg); padding: 2px 8px; border-radius: 10px; font-size: calc(12px * var(--font-scale)); }
.loading { color: var(--muted); font-style: italic; }
#hot-cache-items { list-style: none; max-height: 200px; overflow-y: auto; }
#hot-cache-items li { padding: calc(6px * var(--font-scale)); border-bottom: 1px solid var(--border); font-size: calc(13px * var(--font-scale)); }
</style>
</head>
<body>
<h1>🧠 Engram Dashboard</h1>

<div class="tabs">
  <button class="tab active" onclick="showTab('overview')">Overview</button>
  <button class="tab" onclick="showTab('layer1')">Layer 1: Hot Cache</button>
  <button class="tab" onclick="showTab('layer2')">Layer 2: Semantic</button>
  <button class="tab" onclick="showTab('layer3')">Layer 3-5</button>
  <button class="tab" onclick="showTab('search')">🔍 Search</button>
</div>

<div id="overview" class="panel active">
  <div class="card">
    <div class="stat"><span class="stat-label">Status</span><span class="stat-value" id="status">-</span></div>
    <div class="stat"><span class="stat-label">Total Memories</span><span class="stat-value" id="total-memories">-</span></div>
    <div class="stat"><span class="stat-label">Hot Cache</span><span class="stat-value" id="hot-cache-count">-</span></div>
    <div class="stat"><span class="stat-label">Categories</span><span class="stat-value" id="categories">-</span></div>
  </div>
</div>

<div id="layer1" class="panel">
  <div class="card">
    <h2>Layer 1: Hot Cache</h2>
    <p style="color:var(--muted);margin-bottom:8px">Always-injected, high-priority context</p>
    <ul id="hot-cache-items"><li class="loading">Loading...</li></ul>
  </div>
</div>

<div id="layer2" class="panel">
  <div class="card">
    <h2>Layer 2: Semantic Index</h2>
    <div class="stat"><span class="stat-label">Total Indexed</span><span class="stat-value" id="l2-total">-</span></div>
    <div class="stat"><span class="stat-label">Categories</span><span class="stat-value" id="l2-categories">-</span></div>
    <div class="stat"><span class="stat-label">Embedding Model</span><span class="stat-value" id="l2-model">-</span></div>
  </div>
</div>

<div id="layer3" class="panel">
  <div class="card">
    <h2>Layers 3-5: Coming Soon</h2>
    <p style="color:var(--muted)">
      Layer 3: Procedural (workflows) — planned<br>
      Layer 4: Episodic (transcripts) — planned<br>
      Layer 5: Meta/Reflective (self-improving) — planned
    </p>
  </div>

<div id="search" class="panel">
  <div class="card">
    <h2>🔍 Search Memories</h2>
    <div style="display:flex;gap:8px;margin:12px 0">
      <input id="search-input" type="text" placeholder="Search memories..." style="flex:1;padding:8px;background:var(--bg);border:1px solid var(--border);color:var(--text);font-size:inherit;border-radius:4px" onkeydown="if(event.key===Enter)searchMemories()">
      <button onclick="searchMemories()" style="padding:8px 16px;background:var(--accent);color:var(--bg);border:none;border-radius:4px;cursor:pointer;font-size:inherit">Search</button>
    </div>
    <div id="search-status" style="color:var(--muted);margin-bottom:8px"></div>
    <div id="search-results"></div>
  </div>
</div>
</div>

<script>
function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelector(`.tab:nth-child(${{'overview':1,'layer1':2,'layer2':3,'layer3':4,'search':5}[name]})`).classList.add('active');
  document.getElementById(name).classList.add('active');
  if (name === 'layer1') refreshLayer1();
  if (name === 'layer2') refreshLayer2();
}

async function refresh() {
  try {
    const stats = await fetch('/stats').then(r => r.json());
    const layers = await fetch('/layers').then(r => r.json());
    document.getElementById('status').textContent = 'Running';
    document.getElementById('status').style.color = 'var(--green)';
    document.getElementById('total-memories').textContent = stats.semantic_index.total_memories;
    document.getElementById('hot-cache-count').textContent = stats.hot_cache_size;
    document.getElementById('categories').textContent = stats.semantic_index.categories.join(', ') || 'none';
    // Store for tab refresh
    window._stats = stats;
    window._layers = layers;
  } catch(e) {
    document.getElementById('status').textContent = 'Offline';
    document.getElementById('status').style.color = 'var(--orange)';
  }
}

async function refreshLayer1() {
  try {
    const recall = await fetch('/recall', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({query:'current',layers:[1]}) }).then(r => r.json());
    const ul = document.getElementById('hot-cache-items');
    ul.innerHTML = '';
    if (recall.hot_cache && recall.hot_cache.length) {
      recall.hot_cache.forEach(m => { const li = document.createElement('li'); li.textContent = m; ul.appendChild(li); });
    } else {
      ul.innerHTML = '<li style="color:var(--muted)">No hot cache items</li>';
    }
  } catch(e) {}
}

async function refreshLayer2() {
  try {
    const stats = await fetch('/stats').then(r => r.json());
    document.getElementById('l2-total').textContent = stats.semantic_index.total_memories;
    document.getElementById('l2-categories').textContent = stats.semantic_index.categories.join(', ') || 'none';
    document.getElementById('l2-model').textContent = stats.semantic_index.embedding_model;
  } catch(e) {}
}

async function searchMemories() {
  const q = document.getElementById("search-input").value.trim();
  if (!q) return;
  const status = document.getElementById("search-status");
  const results = document.getElementById("search-results");
  status.textContent = "Searching...";
  results.innerHTML = "";
  try {
    const resp = await fetch("/recall", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({query:q, min_score:0.2}) });
    const data = await resp.json();
    status.textContent = data.count + ' results for "' + q + '"';
    if (!data.semantic_hits || !data.semantic_hits.length) {
      results.innerHTML = "<p style=\"color:var(--muted)\">No results found.</p>";
      return;
    }
    data.semantic_hits.forEach(h => {
      const div = document.createElement("div");
      div.style.cssText = "padding:8px;border-bottom:1px solid var(--border);margin-bottom:4px";
      div.innerHTML = "<div style=\"display:flex;justify-content:space-between\"><strong>" + h.content + "</strong><span style=\"color:var(--accent);font-size:0.9em\">" + h.score.toFixed(3) + "</span></div><div style=\"color:var(--muted);font-size:0.85em\">" + h.category + "</div>";
      results.appendChild(div);
    });
  } catch(e) {
    status.textContent = "Error: " + e.message;
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""
