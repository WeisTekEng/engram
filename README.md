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

### Layer 1: Hot Cache
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Server health check |
| GET | `/stats` | Memory stats (count, categories, persistence) |
| GET | `/layers` | List all available layers |

### Layer 2: Semantic Index
| Method | Path | Description |
|--------|------|-------------|
| POST | `/remember` | Store a memory `{"text": "...", "category": "general"}` |
| POST | `/recall` | Search memories `{"query": "...", "category": "all", "limit": 5}` |
| POST | `/forget` | Delete a memory `{"text": "..."}` |

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
| POST | `/episodes/list` | List all episodes |

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
| POST | `/skills/list` | List all indexed skills |
| POST | `/skills/index` | Re-index skills from Hermes skills directory |

### Dashboard
| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard` | React SPA with 8 tabs (Overview, Layers 1-5, Skills, Search) |

## Running

```bash
cd engram_memory
pip install -e .
python -m engram.server --port 8092
```

Env vars:
- `ENGRAM_DATA_DIR` — ChromaDB persistence path (default: `~/.hermes/engram_data/`)
- `ENGRAM_SKILLS_DIR` — Path to Hermes skills for `/skills/index`

## Tech Stack

- **Python 3.11+** — stdlib `http.server` (zero external server deps for core)
- **ChromaDB** — embedded vector DB (all-MiniLM-L6-v2, 384-dim)
- **React + Vite + TypeScript** — dashboard SPA
- **Sentence Transformers** — embedding generation

## Status

🟢 Active — all 5 layers live with 463+ memories. Dashboard at `/dashboard`.

## License

MIT
