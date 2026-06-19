# Engram Architecture

## Problem

Hermes Agent currently injects ALL memory (MEMORY.md + USER.md) into every turn via the system prompt. This is brute-force: every byte of memory costs a token every single turn. At ~3,000 chars of memory and 100 turns/day, that's ~75K wasted tokens/day on irrelevant context.

The solution: layered retrieval with token-aware injection.

## Layer Design

### Layer 1: Hot Cache
- Always injected, fixed ~200 char ceiling
- Contains: current task context, active constraints, user's immediate preferences
- Edit policy: agent can add/remove, but strict cap enforced
- **Status:** 🟢 Live — `/health`, `/stats`, `/layers` endpoints

### Layer 2: Semantic Index
- Vector embeddings for all durable memories
- Injected ONLY when cosine similarity > threshold against current query
- Storage: ChromaDB (embedded, no server)
- Embedding model: all-MiniLM-L6-v2 (384-dim)
- **Status:** 🟢 Live — `/remember`, `/recall`, `/forget` endpoints. 463+ memories across 10 categories.

### Layer 3: Procedural Memory
- Reusable workflows, how-to procedures, skill schemas
- Triggered by task type matching
- Each procedure has: text, steps (list), tags
- **Status:** 🟢 Live — `/procedures/remember`, `/procedures/search`, `/procedures/list` endpoints

### Layer 4: Episodic Memory
- Timestamped session summaries and key events
- Searchable by keyword and time range
- Each episode has: text, summary, tags, timestamp
- **Status:** 🟢 Live — `/episodes/remember`, `/episodes/search`, `/episodes/list` endpoints

### Layer 5: Reflective
- Self-improvement insights from past sessions
- Pattern recognition, corrections, lessons learned
- Each reflection has: text, insight, action
- **Status:** 🟢 Live — `/reflect`, `/reflections/search`, `/reflections/list` endpoints

## Token Budget Model

On every turn:
1. Hot Cache always loaded (200 chars)
2. Query → embedding → similarity search against Layer 2
3. Top-N results sorted by relevance, trimmed to fit remaining budget
4. Procedural match appended if task type recognized
5. Full context injected into system prompt

## API Design

All endpoints at `http://<host>:8092/`. JSON request/response. Single Python file: `engram/server.py` — uses stdlib `http.server.BaseHTTPRequestHandler` (zero framework dependencies for core).

### Category Prefix Convention

Memories stored in ChromaDB use category prefixes to enable filtered recall:
- `general` — uncategorized facts
- `environment` — system config, paths, tool versions
- `project` — project-specific context
- `skill` — agent skills and capabilities
- `user_preference` — user preferences
- `user_profile` — user identity and details
- `lesson_learned` — mistakes and corrections
- `layer3_procedural` — Layer 3 procedures
- `layer4_episodic` — Layer 4 episodes
- `layer5_reflection` — Layer 5 reflections

### Dashboard

React SPA at `/dashboard` served from `dashboard/dist/`. 8 tabs:
1. Overview — stats, memory counts, category breakdown
2. Layer 1 — Hot Cache viewer
3. Layer 2 — Semantic search with scores
4. Layer 3 — Procedural (search + list)
5. Layer 4 — Episodic (search + list)
6. Layer 5 — Reflective (search + list)
7. Skills — skill listing and search
8. Search — unified cross-layer search

## Storage

- **ChromaDB** (primary): Embedded vector DB, Python-native. Persists to `ENGRAM_DATA_DIR/semantic_index/`
- **Embedding model**: all-MiniLM-L6-v2 (384 dimensions, ~120MB)
- **All layers** share the same ChromaDB collection, differentiated by category prefix

## Integration with Hermes Agent

### Current
- **Skills**: Engram indexes all Hermes skills via `/skills/index`. Hermes' `/skills/list` endpoint queries Engram's ChromaDB instead of SQLite.
- **Memory tool**: Agent dual-writes to both Hermes internal memory and Engram `/remember`.
- **Recall**: Agent queries Engram `/recall` for semantic memory when context is needed.

### Future
- Replace Hermes memory injection with Engram Layer 1-2 pipeline
- Automatic Layer 4 → 5 summarization cron job
- Conflict detection and memory deduplication in Layer 5

## Running

```bash
cd engram_memory
pip install -e .              # installs engram package + deps
python -m engram.server       # starts on port 8092

# For the dashboard:
cd dashboard
npm install && npm run build  # builds to dist/
```

Env vars:
- `ENGRAM_DATA_DIR` — ChromaDB persistence (default: `~/.hermes/engram_data/`)
- `ENGRAM_SKILLS_DIR` — Hermes skills path for indexing
- `ENGRAM_PORT` — Listen port (default: 8092)

## Implementation History

| Phase | What | Status |
|-------|------|--------|
| 1 | Layer 2 Semantic Index + ChromaDB | ✅ Complete |
| 2 | Skills indexing and `/skills/*` endpoints | ✅ Complete |
| 3 | React dashboard (8 tabs, mobile-first) | ✅ Complete |
| 4 | Layers 3, 4, 5 endpoints | ✅ Complete |
| 5 | Agent memory → Engram dual-write | 🔄 In progress |
| 6 | Layer 4→5 auto-summarization | 📋 Planned |
| 7 | Memory conflict detection | 📋 Planned |
