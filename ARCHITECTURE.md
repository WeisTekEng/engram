# Engram Architecture

## Problem

Hermes Agent currently injects ALL memory (MEMORY.md + USER.md) into every turn via the system prompt. This is brute-force: every byte of memory costs a token every single turn. At ~3,000 chars of memory and 100 turns/day, that's ~75K wasted tokens/day on irrelevant context.

The solution: layered retrieval with token-aware injection.

## Layer Design

### Layer 1: Hot Cache
- Always injected, fixed ~200 char ceiling
- Contains: current task context, active constraints, user's immediate preferences
- Edit policy: agent can add/remove, but strict cap enforced

### Layer 2: Semantic Index
- Vector embeddings for all durable memories
- Injected ONLY when cosine similarity > threshold against current query
- Storage: ChromaDB or LanceDB (embedded, no server)
- Embedding model: configurable (default: all-MiniLM-L6-v2 or OpenAI ada-002)

### Layer 3: Procedural Memory
- Reusable workflows (templates, patterns, scripts)
- Triggered by task type matching
- Equivalent to Hermes "skills" but with automatic discovery

### Layer 4: Episodic Memory
- Full conversation transcripts with FTS5 indexing
- Accessed via session_search equivalent
- Used for "what did we discuss about X?" queries

### Layer 5: Meta / Reflective
- Periodic summarization pass over Layer 4
- Extracts durable facts → upserts into Layer 2
- Deduplicates and merges conflicting memories

## Token Budget Model



On every turn:
1. Hot Cache always loaded (200 chars)
2. Query → embedding → similarity search against Layer 2
3. Top-N results sorted by relevance, trimmed to fit remaining budget
4. Procedural match appended if task type recognized
5. Full context injected into system prompt

## Implementation Plan

1. **Phase 1**: Layer 2 (Semantic Index) — biggest win
2. **Phase 2**: Layer 5 (Meta/Reflective) — automated fact extraction
3. **Phase 3**: Layer 1 improvement (dynamic Hot Cache)
4. **Phase 4**: Layer 3-4 integration with existing Hermes systems

## Storage

- **ChromaDB** (default): Lightweight embedded vector DB, Python-native
- **LanceDB** (alternative): Columnar, faster for filtered queries
- **SQLite + FTS5**: For episodic layer metadata

## API Surface (Planned)


