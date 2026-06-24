"""Engram HTTP server — keeps Engram alive as a long-running daemon.

Exposes REST API for memory operations and serves the dashboard.
"""

import json
import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from typing import Optional

from .core import Engram

logger = logging.getLogger(__name__)


class _Handler(BaseHTTPRequestHandler):
    """HTTP request handler for Engram server."""

    # Set by EngramServer before starting
    engram: Engram = None
    dashboard_html: str = ""

    # Metrics tracking: query log + aggregate stats
    _metrics_lock = threading.Lock()
    _metrics_queries: list = []  # list of {ts, query, count, top_score, categories}
    _metrics_remembers: list = []  # list of {ts, merged}
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
            rs = list(cls._metrics_remembers)

        # Remember metrics always available
        rem_total = len(rs)
        rem_merged = sum(1 for r in rs if r["merged"])
        remember = {
            "remember_total": rem_total,
            "remember_merged": rem_merged,
            "merge_rate": round(rem_merged / rem_total, 3) if rem_total else 0,
        }

        if not qs:
            return {
                "total_queries": 0, "hit_rate": 0, "hits": 0, "misses": 0,
                "avg_score": 0, "min_score": 0, "max_score": 0, "median_score": 0,
                "category_distribution": {}, "recent_queries": [],
                **remember,
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
            **remember,
        }

    @classmethod
    def _log_remember(cls, merged: bool):
        """Track /remember outcomes for merge-rate metrics."""
        with cls._metrics_lock:
            cls._metrics_remembers.append({
                "ts": time.time(),
                "merged": merged,
            })
            if len(cls._metrics_remembers) > cls._metrics_max_queries:
                cls._metrics_remembers = cls._metrics_remembers[-cls._metrics_max_queries:]

    @classmethod
    def _get_remember_metrics(cls) -> dict:
        with cls._metrics_lock:
            rs = list(cls._metrics_remembers)
        total = len(rs)
        merged = sum(1 for r in rs if r["merged"])
        return {
            "remember_total": total,
            "remember_merged": merged,
            "merge_rate": round(merged / total, 3) if total else 0,
        }

    def _count_sessions(self) -> int:
        """Count L4 episodic sessions using list_by_category (substring-aware)."""
        items = self.engram._semantic.list_by_category("L4_", limit=1000)
        seen = set()
        for item in items:
            sid = (item.get("metadata", {}) or {}).get("session_id", "")
            if sid:
                seen.add(sid)
        return len(seen)

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
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.warning("_read_json: %s on %d-byte body", e, length)
            return {}  # graceful fallback — don't crash the server

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            stats = self.engram.stats()
            uptime = int(time.time() - type(self)._start_time)
            layers_data = stats["layers"]

            # Actually probe health — don't blindly report "ok"
            checks = {}
            # Check 1: ChromaDB is reachable
            try:
                chroma_count = self.engram._semantic.collection.count()
                checks["chromadb"] = {"status": "ok", "count": chroma_count}
            except Exception as e:
                checks["chromadb"] = {"status": "error", "error": str(e)[:200]}

            # Check 2: Consolidation thread is alive (if enabled)
            cons = stats.get("consolidation", {})
            checks["consolidation"] = {
                "enabled": cons.get("enabled", False),
                "thread_alive": cons.get("thread_alive", False),
            }

            # Determine overall status
            chroma_ok = checks["chromadb"]["status"] == "ok"
            cons_ok = (
                not checks["consolidation"]["enabled"]
                or checks["consolidation"]["thread_alive"]
            )
            overall = "ok" if (chroma_ok and cons_ok) else "degraded"

            self._json({
                "status": overall,
                "checks": checks,
                "layers": {
                    "1": {"name": "hot_cache", "count": layers_data.get("L1_hot", 0)},
                    "2": {"name": "semantic_index", "count": layers_data.get("L2_semantic", 0)},
                    "3": {"name": "procedural", "count": layers_data.get("L3_procedural", 0)},
                    "4": {"name": "episodic", "count": layers_data.get("L4_episodic", 0)},
                    "5": {"name": "reflection", "count": layers_data.get("L5_reflection", 0)},
                },
                "total_memories": stats["semantic_index"]["total_memories"],
                "dedup": {
                    "merged_total": self.engram._dedup_merged_count,
                },
                "uptime_seconds": uptime,
            })

        elif path == "/hot-cache":
            # Return raw L1 hot cache items (no query filter)
            items = list(self.engram._hot_cache)
            self._json({
                "items": items[-15:],  # last 15 (matches _HOT_CACHE_RETURN)
                "total": len(items),
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

        elif path == "/export":
            # Export all memories as JSON (backup/round-trip)
            all_data = self.engram._semantic.collection.get(
                include=["metadatas", "documents"]
            )
            memories = []
            if all_data and all_data["ids"]:
                for i, mem_id in enumerate(all_data["ids"]):
                    meta = (all_data["metadatas"] or [{}])[i] or {}
                    memories.append({
                        "id": mem_id,
                        "content": (all_data["documents"] or [""])[i] or "",
                        "category": meta.get("category", "general"),
                        "importance": float(meta.get("importance", 0.5)),
                        "access_count": int(meta.get("access_count", 0)),
                        "created_at": meta.get("created_at", ""),
                        "metadata": {
                            k: v for k, v in meta.items()
                            if k not in ("category", "importance", "created_at",
                                         "access_count", "content_hash")
                        },
                    })
            self._json({
                "exported_at": datetime.now().isoformat(),
                "total": len(memories),
                "memories": memories,
            })

        elif path == "/skills" or path == "/skills/list":
            # GET skills list (for dashboard browsing)
            import traceback as _tb2
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
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
            self._json({"skills": skills, "count": len(skills), "error": error_msg})

        elif path == "/episodes/list":
            # GET: list all episodes (L4) — real listing, no fake query
            items = self.engram._semantic.list_by_category("L4_", limit=100)
            episodes = []
            seen = set()
            for item in items:
                if item["content"] in seen:
                    continue
                seen.add(item["content"])
                meta = item.get("metadata", {})
                title = meta.get("title", "")
                if not title:
                    first_line = item["content"].split("\n")[0].strip("# ").strip()
                    if len(first_line) > 3:
                        title = first_line[:80]
                    else:
                        title = item["content"][:80].replace(" | ", " ").strip()
                episodes.append({
                    "title": title,
                    "content": item["content"][:300],
                    "timestamp": meta.get("timestamp", ""),
                    "tags": meta.get("tags", ""),
                    "outcome": meta.get("outcome", ""),
                    "session_id": meta.get("session_id", ""),
                    "score": round(item.get("importance", 0.5), 3),
                })
            self._json({"episodes": episodes, "count": len(episodes)})

        elif path == "/reflections/list":
            # GET: list all reflections (L5) — real listing, no fake query
            items = self.engram._semantic.list_by_category("L5_", limit=100)
            reflections = []
            seen = set()
            for item in items:
                if item["content"] in seen:
                    continue
                seen.add(item["content"])
                meta = item.get("metadata", {})
                reflections.append({
                    "topic": meta.get("topic", ""),
                    "content": item["content"][:200],
                    "insight": meta.get("insight", ""),
                    "action": meta.get("action", ""),
                    "success": meta.get("success", ""),
                    "score": round(item.get("importance", 0.5), 3),
                })
            self._json({"reflections": reflections, "count": len(reflections)})

        elif path == "/procedures/list":
            # GET: list all procedures (L3) — real listing, no fake query
            items = self.engram._semantic.list_by_category("L3_", limit=200)
            procedures = []
            seen = set()
            for item in items:
                if item["content"] in seen:
                    continue
                seen.add(item["content"])
                meta = item.get("metadata", {})
                procedures.append({
                    "name": meta.get("name", ""),
                    "content": item["content"][:200],
                    "steps": meta.get("steps", ""),
                    "domain": meta.get("domain", ""),
                    "score": round(item.get("importance", 0.5), 3),
                })
            self._json({"procedures": procedures, "count": len(procedures)})

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
            info = self.engram.remember_with_info(
                content=data.get("content", ""),
                layer=data.get("layer", 2),
                category=data.get("category", "general"),
                importance=data.get("importance", 0.5),
                metadata=data.get("metadata"),
            )
            # Track merge behavior for /metrics
            self._log_remember(merged=info["merged"])
            resp = {"memory_id": info["memory_id"], "merged": info["merged"]}
            if info["merged"]:
                resp["status"] = "merged"
                resp["new_importance"] = info.get("new_importance", 0.5)
            else:
                resp["status"] = "stored"
            self._json(resp)

        elif path == "/recall":
            data = self._read_json()
            result = self.engram.recall(
                query=data.get("query", ""),
                layers=data.get("layers"),
                limit=data.get("limit", 10),
                min_score=data.get("min_score", 0.3),
            )
            # Auto-log metrics from unified results
            unified = result.unified
            self._log_query(
                query=data.get("query", ""),
                count=len(unified),
                top_score=unified[0]["score"] if unified else 0,
                categories=[u.get("category","") for u in unified[:5]],
            )
            self._json({
                "query": data.get("query", ""),
                "count": len(unified),
                "hot_cache": result.hot_cache,
                "semantic_hits": [
                    {"content": h.memory.content, "score": h.score, "category": h.memory.category}
                    for h in result.semantic_hits
                ],
                "procedural": result.procedural_matches,
                "episodic": result.episodic_matches,
                "reflections": result.reflection_matches,
                "unified": unified[:data.get("limit", 10)],
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
            # Filter to only skill-category memories from ALL layers (unified crosses L2-L5)
            skill_hits = [
                {"name": item.get("metadata", {}).get("skill_name", ""),
                 "description": item["content"],
                 "score": item["score"],
                 "category": item.get("metadata", {}).get("skill_category", "")}
                for item in result.unified
                if "skill" in (item.get("category", "") or "")
            ]
            self._json({
                "query": data.get("query", ""),
                "count": len(skill_hits),
                "skills": skill_hits,
            })

        elif path == "/skills/index":
            # Index all skills from disk into Engram
            import os as _os4
            import hashlib as _hl
            skills_dir = _os4.path.join(_os4.path.dirname(_os4.path.abspath(__file__)), "..", "..", ".hermes", "skills")
            # Respect ENGRAM_SKILLS_DIR env var if set (portability — no hardcoded paths)
            env_skills = _os4.environ.get("ENGRAM_SKILLS_DIR", "")
            if env_skills and _os4.path.isdir(env_skills):
                skills_dir = env_skills
            indexed = 0
            skipped_dupes = 0
            content_hashes = set()
            if _os4.path.isdir(skills_dir):
                for root, dirs, files in _os4.walk(skills_dir):
                    for f in files:
                        if f == "SKILL.md":
                            skill_path = _os4.path.join(root, f)
                            skill_name = _os4.path.basename(root)
                            try:
                                with open(skill_path, encoding="utf-8") as sf:
                                    content = sf.read()
                                # Dedup guard: skip if identical content hash already seen
                                content_hash = _hl.sha256(content.encode()).hexdigest()
                                if content_hash in content_hashes:
                                    skipped_dupes += 1
                                    continue
                                content_hashes.add(content_hash)
                                # Extract description (first paragraph after frontmatter)
                                desc = content
                                if content.startswith("---"):
                                    parts = content.split("---", 2)
                                    if len(parts) >= 3:
                                        desc = parts[2].strip().split("\n\n")[0][:500]
                                self.engram._push_hot(desc)
                                self.engram._semantic.remember(
                                    content=desc,
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
            self._json({"status": "indexed", "count": indexed, "skipped_duplicates": skipped_dupes})

        elif path == "/skills/list" or path == "/skills/list/":
            # Real listing via list_by_category — deterministic, no fake query
            import traceback as _tb
            skills = []
            error_msg = None
            try:
                # Skills can have any of these category prefixes after consolidation
                prefixes = ["skill", "procedural_skill", "episodic_skill",
                           "reflection_skill", "L3_procedural_skill",
                           "L4_episodic_skill", "L5_reflection_skill"]
                seen = set()
                for prefix in prefixes:
                    items = self.engram._semantic.list_by_category(prefix, limit=500)
                    for item in items:
                        name = (item.get("metadata", {}) or {}).get("skill_name", "")
                        if name and name not in seen:
                            seen.add(name)
                            skills.append({
                                "name": name,
                                "description": item["content"][:200] if item.get("content") else "",
                                "category": (item.get("metadata", {}) or {}).get("skill_category", ""),
                                "score": round(item.get("importance", 0.5), 3),
                            })
                error_msg = f"prefixes checked: {len(prefixes)}, found: {len(skills)}"
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
            self._json({"skills": skills, "count": len(skills), "error": error_msg})

        # ── Session → L4 auto-feed ──
        elif path == "/sessions/complete":
            # Called after a Hermes session ends to auto-store an episodic summary.
            # Auto-promotes key decisions and outcomes into L4 episodic memory.
            # Idempotent: if session_id is provided and already exists, returns existing record.
            data = self._read_json()
            summary = data.get("summary", "")
            decisions = data.get("decisions", [])
            files_changed = data.get("files_changed", [])
            outcome = data.get("outcome", "completed")
            session_id = data.get("session_id", "")
            timestamp = data.get("timestamp", "")

            if not summary:
                self._json({"status": "error", "message": "summary required"})
                return

            # Check for existing session_id (idempotency gate)
            if session_id:
                existing = self.engram._semantic.list_by_category("L4_", limit=500)
                for item in existing:
                    meta = item.get("metadata", {}) or {}
                    if meta.get("session_id") == session_id:
                        self._json({
                            "status": "already_recorded",
                            "memory_id": item["id"],
                            "layer": 4,
                            "total_sessions": self._count_sessions(),
                        })
                        return

            # Build structured episodic content
            parts = [f"Session: {session_id}", f"Outcome: {outcome}"]
            if decisions:
                parts.append("Key decisions: " + "; ".join(decisions[:5]))
            if files_changed:
                parts.append(f"Files changed: {len(files_changed)}")
            parts.append(summary)

            content = " | ".join(parts)

            memory_id = self.engram._semantic.remember(
                content=content,
                category="L4_episodic_session",
                importance=data.get("importance", 0.75),
                metadata={
                    "session_id": session_id,
                    "timestamp": timestamp,
                    "outcome": outcome,
                    "title": data.get("title", summary[:80]),
                    "tags": ",".join(data.get("tags", [])[:10]),
                    "decisions": ",".join(decisions[:5]),
                    "files_changed_count": str(len(files_changed)),
                    "source": "hermes-session-auto-feed",
                },
            )

            self._json({
                "status": "stored",
                "memory_id": memory_id,
                "layer": 4,
                "total_sessions": self._count_sessions(),
            })

        # ── Layer 3: Procedural Memory (workflows) ──

        elif path == "/procedures/remember":
            data = self._read_json()
            memory_id = self.engram._semantic.remember(
                content=data.get("content", ""),
                category="L3_procedural_procedural",
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
            result = self.engram.recall(
                query=data.get("query", ""),
                layers=[3],
                limit=30,
                min_score=data.get("min_score", 0.2),
            )
            hits = [{"name": "", "content": r[:300], "steps": "", "domain": "", "score": 1.0}
                    for r in result.procedural_matches[:20]]
            self._json({"query": data.get("query", ""), "count": len(hits), "procedures": hits})

        elif path == "/procedures/list":
            items = self.engram._semantic.list_by_category("L3_", limit=200)
            seen = set()
            procedures = []
            for item in items:
                if item["content"] in seen:
                    continue
                seen.add(item["content"])
                meta = item.get("metadata", {})
                procedures.append({
                    "name": meta.get("name", ""),
                    "content": item["content"][:200],
                    "domain": meta.get("domain", ""),
                    "score": round(item.get("importance", 0.5), 3),
                })
            self._json({"procedures": procedures, "count": len(procedures)})

        # ── Layer 4: Episodic Memory (sessions/events) ──

        elif path == "/episodes/remember":
            data = self._read_json()
            memory_id = self.engram._semantic.remember(
                content=data.get("content", ""),
                category="L4_episodic_session",
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
            result = self.engram.recall(
                query=data.get("query", ""),
                layers=[4],
                limit=30,
                min_score=data.get("min_score", 0.2),
            )
            hits = [{"title": "", "content": r[:300], "session_id": "", "timestamp": "",
                     "tags": "", "outcome": "", "score": 1.0}
                    for r in result.episodic_matches[:20]]
            self._json({"query": data.get("query", ""), "count": len(hits), "episodes": hits})

        elif path == "/episodes/list":
            # Real listing via list_by_category — no fake query, deterministic results
            try:
                items = self.engram._semantic.list_by_category("L4_", limit=100)
                seen = set()
                episodes = []
                for item in items:
                    if item["content"] in seen:
                        continue
                    seen.add(item["content"])
                    meta = item.get("metadata", {})
                    title = meta.get("title", "")
                    timestamp = meta.get("timestamp", "")
                    tags = meta.get("tags", "")
                    outcome = meta.get("outcome", "")
                    sid = meta.get("session_id", "")
                    if not title:
                        first_line = item["content"].split("\n")[0].strip("# ").strip()
                        if len(first_line) > 3:
                            title = first_line[:80]
                        else:
                            title = item["content"][:80].replace(" | ", " ").strip()
                    episodes.append({
                        "title": title,
                        "content": item["content"][:300],
                        "timestamp": timestamp,
                        "tags": tags,
                        "outcome": outcome,
                        "session_id": sid,
                        "score": round(item.get("importance", 0.5), 3),
                    })
                self._json({"episodes": episodes, "count": len(episodes)})
            except Exception as e:
                import traceback
                self._json({"episodes": [], "count": 0, "error": str(e), "trace": traceback.format_exc()[-300:]})

        # ── Layer 5: Meta/Reflective Memory ──

        elif path == "/reflect":
            data = self._read_json()
            memory_id = self.engram._semantic.remember(
                content=data.get("content", ""),
                category="L5_reflection_insight",
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
            result = self.engram.recall(
                query=data.get("query", ""),
                layers=[5],
                limit=30,
                min_score=data.get("min_score", 0.2),
            )
            hits = [{"topic": "", "content": r[:300], "insight": "", "action": "",
                     "success": "", "score": 1.0}
                    for r in result.reflection_matches[:20]]
            self._json({"query": data.get("query", ""), "count": len(hits), "reflections": hits})

        elif path == "/reflections/list":
            items = self.engram._semantic.list_by_category("L5_", limit=100)
            seen = set()
            reflections = []
            for item in items:
                if item["content"] in seen:
                    continue
                seen.add(item["content"])
                meta = item.get("metadata", {})
                reflections.append({
                    "topic": meta.get("topic", ""),
                    "content": item["content"][:200],
                    "insight": meta.get("insight", ""),
                    "action": meta.get("action", ""),
                    "success": meta.get("success", ""),
                    "score": round(item.get("importance", 0.5), 3),
                })
            self._json({"reflections": reflections, "count": len(reflections)})

        elif path == "/metrics/log":
            data = self._read_json()
            self._log_query(
                query=data.get("query", ""),
                count=data.get("count", 0),
                top_score=data.get("top_score", 0),
                categories=data.get("categories", []),
            )
            self._json({"status": "logged"})

        elif path == "/consolidate":
            result = self.engram.trigger_consolidation()
            self._json(result)

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
        # Track startup time for /health uptime reporting (on handler class, not HTTPServer)
        self._start_time = time.time()
        _Handler._start_time = self._start_time

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
  <button class="tab" onclick="showTab('how')">❓ How</button>
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

<div id="how" class="panel">
  <div class="card">
    <h2>🧠 How Engram Works</h2>
    <div style="font-size:calc(13px*var(--font-scale));line-height:1.7;color:var(--text)">

      <h3>5 Layers — Automated Pipeline</h3>
      <p>Engram is a self-contained memory system with NO external cron jobs. Everything runs inside the process.</p>

      <div style="margin:12px 0;padding:10px;background:rgba(88,166,255,0.08);border-left:3px solid var(--accent);border-radius:4px">
        <strong>Layer 1: Hot Cache</strong> (in-memory, persisted to disk)<br>
        <span style="color:var(--muted)">Auto-populated from every write and every recall top-hit. Last 30 items kept, last 15 returned.</span>
      </div>

      <div style="margin:12px 0;padding:10px;background:rgba(88,166,255,0.08);border-left:3px solid var(--accent);border-radius:4px">
        <strong>Layer 2: Semantic Index</strong> (ChromaDB)<br>
        <span style="color:var(--muted)">All new memories land here. Queried by embedding similarity (all-MiniLM-L6-v2, cosine distance). Dedup merges at score ≥ 0.85.</span>
      </div>

      <div style="margin:12px 0;padding:10px;background:rgba(108,92,231,0.08);border-left:3px solid #6c5ce7;border-radius:4px">
        <strong>Layer 3: Procedural</strong> (promoted from L2)<br>
        <span style="color:var(--muted)">Memories recalled ≥2 times with importance ≥0.40 auto-promote here. They're workflows and reusable patterns.</span>
      </div>

      <div style="margin:12px 0;padding:10px;background:rgba(0,230,118,0.08);border-left:3px solid var(--success);border-radius:4px">
        <strong>Layer 4: Episodic</strong> (promoted from L3)<br>
        <span style="color:var(--muted)">Memories recalled ≥4 times with importance ≥0.55 promote here. They represent recurring session patterns.</span>
      </div>

      <div style="margin:12px 0;padding:10px;background:rgba(210,153,29,0.08);border-left:3px solid var(--orange);border-radius:4px">
        <strong>Layer 5: Reflection</strong> (promoted from L4)<br>
        <span style="color:var(--muted)">Memories recalled ≥8 times with importance ≥0.70 promote here. These are hardened insights — the most valuable persistent knowledge.</span>
      </div>

      <h3>Automation (no cron)</h3>
      <ul style="color:var(--muted);font-size:calc(12px*var(--font-scale))">
        <li><strong>Dedup-on-write:</strong> semantic merge at 0.85 — same content returns existing ID, importance boosted</li>
        <li><strong>Auto-consolidation:</strong> daemon thread every 30 min — decays memories >30 days old, purges below 0.05 importance</li>
        <li><strong>Layer promotion:</strong> frequently recalled memories auto-graduate L2→L3→L4→L5 based on access count + importance</li>
        <li><strong>L1 persistence:</strong> hot cache saves to disk on shutdown, reloads on startup</li>
        <li><strong>Unified recall:</strong> one API call searches all 5 layers, ranked by combined_score = semantic×0.6 + importance×0.4</li>
      </ul>

      <h3>API Endpoints</h3>
      <div style="font-size:calc(11px*var(--font-scale));background:var(--bg);padding:8px;border-radius:4px">
        POST /remember — store (cat, importance, layer)<br>
        POST /recall — search all layers (query, limit, min_score)<br>
        POST /consolidate — manual trigger<br>
        GET /stats — layer counts + consolidation status<br>
        GET /health — alive check<br>
        POST /skills/search — find relevant skills<br>
        POST /procedures/remember — store workflow<br>
        POST /episodes/remember — store session<br>
        POST /reflect — store insight
      </div>
    </div>
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
  const idx = {{'overview':1,'layer1':2,'layer2':3,'how':4,'search':5}[name] || 4};
  document.querySelector(`.tab:nth-child(${idx})`).classList.add('active');
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
