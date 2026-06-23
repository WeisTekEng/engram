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
- **Status:** 🟢 Live — `/remember`, `/recall`, `/forget` endpoints. 290+ memories across 10+ categories.

### Layer 3: Procedural Memory
- Reusable workflows, how-to procedures, skill schemas
- Triggered by task type matching
- Each procedure has: text, steps (list), tags
- **Status:** 🟢 Live — `/procedures/remember`, `/procedures/search`, `/procedures/list` endpoints. 74+ stored procedures.

### Layer 4: Episodic Memory
- Timestamped session summaries and key events
- Searchable by keyword and time range
- Each episode has: text, summary, tags, timestamp, outcome
- Auto-fed via `/sessions/complete` from Hermes Agent at session end
- **Status:** 🟢 Live — `/episodes/remember`, `/episodes/search`, `/episodes/list`, `/sessions/complete` endpoints. 73+ episodes.

### Layer 5: Reflective
- Self-improvement insights from past sessions
- Pattern recognition, corrections, lessons learned
- Each reflection has: text, insight, action
- **Status:** 🟢 Live — `/reflect`, `/reflections/search`, `/reflections/list` endpoints. 20+ reflections.

## Token Budget Model

On every turn:
1. Hot Cache always loaded (200 chars)
2. Query → embedding → similarity search against Layer 2
3. Top-N results sorted by relevance, trimmed to fit remaining budget
4. Procedural match appended if task type recognized
5. Full context injected into system prompt

## Dedup Pipeline

### Three-Layer Dedup Strategy

1. **SHA256 Content-Hash Dedup** (write-time, `/skills/index`)
   - Identical SKILL.md files skipped within a single index run
   - Prevents double-scan duplicates (same dir reached via different paths)

2. **Semantic Dedup** (write-time, `Engram.remember()`)
   - Checks ≥85% cosine similarity against existing memories
   - If match found: boosts existing importance, skips new store
   - **Bypassed for skills**: SKILL.md files share similar structure (frontmatter + sections) causing false semantic matches. `/skills/index` calls `_semantic.remember()` directly to bypass.

3. **Consolidation** (background daemon, every 30 min)
   - Promotes frequently-accessed memories to higher layers
   - Decays stale memories (30 days without access)
   - Auto-purges below minimum importance (0.05)

### Consolidation Thresholds
| Promotion | Min Recalls | Min Importance |
|-----------|-------------|----------------|
| L2 → L3 (Procedural) | 4 | 0.55 |
| L3 → L4 (Episodic) | 8 | 0.70 |
| L4 → L5 (Reflective) | 12 | 0.80 |

## Category Prefix Convention

Memories stored in ChromaDB use category prefixes. Consolidation prepends layer prefixes:

**Base categories** (as stored):
- `general` — uncategorized facts
- `environment` — system config, paths, tool versions
- `project` — project-specific context
- `skill` — agent skills and capabilities
- `user_preference` — user preferences
- `user_profile` — user identity and details
- `lesson_learned` — mistakes and corrections

**Consolidation prefixes** (auto-applied on promotion):
- L2 → L3: `procedural_` (e.g., `skill` → `procedural_skill`)
- L3 → L4: `episodic_` (e.g., `skill` → `episodic_skill`)
- L4 → L5: `reflection_` prefix

**Query handling**: Search/list endpoints use substring matching (`"skill" in category`) to match all prefix variants — no more broken filters after consolidation.

## API Design

All endpoints at `http://<host>:8092/`. JSON request/response. Single Python file: `engram/server.py` — uses stdlib `http.server.BaseHTTPRequestHandler` (zero framework dependencies for core).

### Skills Indexing Pipeline

`POST /skills/index` walks the Hermes skills directory, reads each `SKILL.md`, and stores in Engram:

1. Walk `F:/hermes/.hermes/skills/` for all `SKILL.md` files
2. Extract skill name from directory name, category from parent directory
3. Parse frontmatter, extract first paragraph as description
4. SHA256 content-hash check — skip identical duplicates within batch
5. Store via `_semantic.remember()` directly (bypass semantic dedup)
6. Returns `{"count": N, "skipped_duplicates": M}`

**Pitfall avoided**: Using `Engram.remember()` (with semantic dedup) caused skills with similar structure to merge, reducing 115+ skills to ~3. Direct `_semantic.remember()` calls bypass the 85% similarity check.

### Session Auto-Feed

`POST /sessions/complete` called by Hermes Agent at session end:

```json
{
  "summary": "What happened this session",
  "decisions": ["Decision 1", "Decision 2"],
  "files_changed": ["path/to/file.ts"],
  "outcome": "success|partial|blocked",
  "session_id": "optional-unique-id",
  "timestamp": "2026-06-23T12:00:00",
  "title": "Optional session title",
  "tags": ["bug-fix", "skills"]
}
```

Stores directly to Layer 4 episodic memory with full metadata preservation.

### Dashboard

React SPA at `/dashboard` served from `dashboard/dist/`. 9 tabs:
1. Overview — stats, memory counts with dynamic layer breakdown from `/health`
2. Layer 1 — Hot Cache viewer
3. Layer 2 — Semantic search with scores
4. Layer 3 — Procedural (search + list)
5. Layer 4 — Episodic (search + list with metadata: title, tags, timestamp, outcome)
6. Layer 5 — Reflective (search + list)
7. Skills — skill listing (115+ indexed) and semantic search
8. Search — unified cross-layer search
9. How — automation pipeline docs, consolidation thresholds, Hermes-Engram integration flow

## Storage

- **ChromaDB** (primary): Embedded vector DB, Python-native. Persists to `ENGRAM_DATA_DIR/semantic_index/`
- **Embedding model**: all-MiniLM-L6-v2 (384 dimensions, ~120MB)
- **All layers** share the same ChromaDB collection, differentiated by category prefix

## Bootstrap & Warmup

### Environment Bootstrap
`engram/bootstrap_environment.py` pre-loads 10+ high-value environment facts (hostname, services, disk layout, build environment, paths) into L2 on first run. Uses SHA256 content-hash for idempotency — safe to re-run.

### Warmup Script
`engram/tools/warmup_engram.py` fires 15 diverse recall queries to boost access counts for high-importance memories, triggering automatic consolidation promotion.

## Integration with Hermes Agent

### Current
- **Skills**: Engram indexes all Hermes skills via `/skills/index` (115+ skills). Hermes queries Engram's ChromaDB for skill discovery instead of SQLite.
- **Memory tool**: Agent dual-writes to both Hermes internal memory and Engram `/remember`.
- **Engram-first mandate**: Agent ALWAYS queries Engram first for skills+memories. Hermes memory tool is fallback only when Engram is down.
- **Session auto-feed**: Agent calls `/sessions/complete` at end of each session → Layer 4 episodic.

### Future
- Replace Hermes memory injection with Engram Layer 1-2 pipeline
- Automatic Layer 4 → 5 summarization
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
- `ENGRAM_HOST` — Bind address (default: `127.0.0.1`)

## Implementation History

| Phase | What | Status |
|-------|------|--------|
| 1 | Layer 2 Semantic Index + ChromaDB | ✅ Complete |
| 2 | Skills indexing and `/skills/*` endpoints | ✅ Complete |
| 3 | React dashboard (9 tabs, mobile-first) | ✅ Complete |
| 4 | Layers 3, 4, 5 endpoints | ✅ Complete |
| 5 | Agent memory → Engram dual-write + Engram-first mandate | ✅ Complete |
| 6 | Skills dedup bypass (direct ChromaDB writes) | ✅ Complete |
| 7 | Layer 4 episodic metadata fix (title, tags, outcome) | ✅ Complete |
| 8 | Session auto-feed (`/sessions/complete` → L4) | ✅ Complete |
| 9 | Bootstrap environment facts + warmup scripts | ✅ Complete |
| 10 | Consolidation threshold tuning + promotion pipeline | ✅ Complete |
| 11 | Layer 4→5 auto-summarization | 📋 Planned |
| 12 | Memory conflict detection + resolution | 📋 Planned |
