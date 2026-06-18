# Engram

> *"The physical trace a memory leaves in the brain."*

**Engram** is a multi-layered memory architecture for [Hermes Agent](https://github.com/NousResearch/hermes-agent). It gives AI agents durable, retrievable memory traces with intelligent token budgeting — like a frontal cortex for your agent.

## Architecture (5 Layers)

| Layer | Name | Description | Token Impact |
|-------|------|-------------|--------------|
| 1 | **Hot Cache** | Always-injected, high-priority context (~200 chars) | Fixed overhead |
| 2 | **Semantic Index** | Vector-backed retrieval on relevance | Largest savings |
| 3 | **Procedural** | Reusable workflows and patterns (skills) | Avoids re-teaching |
| 4 | **Episodic** | FTS5 over conversation transcripts | Session recall |
| 5 | **Meta / Reflective** | Summarization → fact extraction → Layer 2 upsert | Self-improving |

Layer 2 (Semantic Index) is the biggest lever — instead of dumping ALL memories into every turn, only relevant ones are injected.

## Status

🚧 Pre-alpha — architecture designed, implementation in progress.

## License

MIT
