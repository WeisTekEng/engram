# Engram

> *"The physical trace a memory leaves in the brain."*

**Engram** is a multi-layered memory architecture for [Hermes Agent](https://github.com/NousResearch/hermes-agent). It gives AI agents durable, retrievable memory traces with intelligent token budgeting — like a frontal cortex for your agent.

## Architecture (5 Layers)

| Layer | Name | Description | Token Impact |
|-------|------|-------------|--------------|
| 1 | **Hot Cache** | Always-injected, high-priority context (200 char cap) | Fixed overhead |
| 2 | **Semantic Index** | Vector-backed retrieval via ChromaDB (all-MiniLM-L6-v2) | Largest savings |
| 3 | **Procedural** | Reusable workflows, how-to guides, skill schemas | Avoids re-teaching |
| 4 | **Episodic** | Timestamped session summaries, key events, decisions | Session recall |
| 5 | **Reflective** | Self-improvement insights, pattern recognition, corrections | Self-improving |

Layer 2 (Semantic Index) is the biggest lever — instead of dumping ALL memories into every turn, only relevant ones are injected based on cosine similarity to the current query.

## API

All endpoints at `http://<host>:8092/`. JSON request/response.

### Core Memory
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Server health + layer counts |
| GET | `/stats` | Memory stats (count, categories, persistence) |
| GET | `/layers` | List all available layers |
| POST | `/remember` | Store a memory `{"content": "...", "category": "skill", "importance": 0.7, "metadata": {...}}` |
| POST | `/recall` | Search all layers `{"query": "...", "limit": 10, "min_score": 0.3}` |
| POST | `/forget` | Delete a memory `{"memory_id": "..."}` |

### Layer 3: Procedural
| Method | Path | Description |
|--------|------|-------------|
| POST | `/procedures/remember` | Store a procedure `{"text": "...", "steps": [...], "tags": [...]}` |
| POST | `/procedures/search` | Search procedures `{"query": "..."}` |
| POST | `/procedures/list` | List all procedures |

### Layer 4: Episodic
| Method | Path | Description |
|--------|------|-------------|
| POST | `/episodes/remember` | Store an episode `{"text": "...", "summary": "...", "tags": [...]}` |
| POST | `/episodes/search` | Search episodes `{"query": "..."}` |
| POST | `/episodes/list` | List all episodes with full metadata (title, tags, timestamp, outcome) |
| POST | `/sessions/complete` | Auto-store session summary → Layer 4 episodic |

### Layer 5: Reflective
| Method | Path | Description |
|--------|------|-------------|
| POST | `/reflect` | Store a reflection `{"text": "...", "insight": "...", "action": "..."}` |
| POST | `/reflections/search` | Search reflections `{"query": "..."}` |
| POST | `/reflections/list` | List all reflections |

### Skills
| Method | Path | Description |
|--------|------|-------------|
| POST | `/skills/search` | Semantic skill search `{"query": "..."}` |
| POST | `/skills/list` | List all indexed skills (115+) with names and categories |
| POST | `/skills/index` | Re-index all skills from Hermes skills directory. Uses SHA256 content-hash dedup and direct ChromaDB writes to bypass semantic dedup (avoids >85% similarity merging of similar SKILL.md files) |

### Dashboard
| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard` | React SPA with 9 tabs: Overview, L1-L5, Skills, Search, How |

## Key Features

### Dedup Pipeline
- **Write-time**: SHA256 content-hash dedup in `/skills/index` — identical content skipped within a batch
- **Semantic dedup**: `Engram.remember()` checks ≥85% cosine similarity and boosts importance instead of creating duplicates (disabled for skills via `_semantic.remember()` bypass)
- **Consolidation**: Background daemon promotes frequently-accessed L2 memories to L3/L4/L5 based on recall count and importance thresholds

### Consolidation Thresholds
| Promotion | Min Recalls | Min Importance |
|-----------|-------------|----------------|
| L2 → L3 (Procedural) | 2 | 0.40 |
| L3 → L4 (Episodic) | 4 | 0.55 |
| L4 → L5 (Reflective) | 8 | 0.70 |

### Category Prefix Convention
Consolidation prepends layer prefixes to categories:
- `skill` → `procedural_skill` (L3) or `episodic_skill` (L4)
- `general` → `L3_general`, `L4_general`, etc.
- Search endpoints use substring matching (`"skill" in category`) to handle all variants

## Running

```bash
cd engram_memory
pip install -e .
python -m engram.server --port 8092
```

Env vars:
- `ENGRAM_DATA_DIR` — ChromaDB persistence path (default: `~/.hermes/engram_data/`)
- `ENGRAM_HOST` — Bind address (default: `127.0.0.1`)

## Tech Stack

- **Python 3.11+** — stdlib `http.server` (zero external server deps for core)
- **ChromaDB** — embedded vector DB (all-MiniLM-L6-v2, 384-dim)
- **React + Vite + TypeScript** — dashboard SPA
- **Sentence Transformers** — embedding generation

## Status

🟢 Active — all 5 layers live with 290+ memories, 115 indexed skills. Dashboard at `/dashboard`.

## License

MIT
