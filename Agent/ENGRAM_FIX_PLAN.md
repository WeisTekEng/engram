# Engram — Audit Fix Plan (Phased)

**Audience:** AI coding agent working in the `engram` repo.
**Source:** findings from a manual code audit that traced documentation (README.md, ARCHITECTURE.md) against actual behavior in `core.py`, `server.py`, `layers/semantic_index.py`, and the dashboard.

## How to work through this document

Seven phases, ordered by impact and by dependency (later phases assume earlier ones are done and verified). Phases 1–6 fix confirmed bugs; Phase 7 adds robustness and usefulness improvements on top of a now-correct foundation. **Do not start a phase until the previous one's verification steps pass.** After each phase, report back: what changed, what the new/updated tests assert, and the actual `pytest` output — not a summary claiming success. This codebase already has one doc (`docs`/`REFACTOR_CSS_MODULES.md`-style overstatement problem in spirit, if not by name — ARCHITECTURE.md's promotion thresholds don't match the code that's supposedly implementing them) where written status didn't match reality. Don't add a second instance of that. If something can't be fully fixed in a phase, say so explicitly rather than marking it done.

Every phase requires **new or updated tests that fail on the old code and pass on the fixed code.** A test that would have passed before your fix too is not a meaningful regression test — write tests that pin down the actual bug, not just "the endpoint returns 200."

Match the existing test style: `tests/test_engram.py` for in-process unit tests against `Engram`/`SemanticIndex` directly; `tests/test_server.py` / `tests/test_recall.py` for HTTP-level tests using the `EngramServer` + background-thread + `/health`-polling fixture pattern already established there. Don't invent a third testing style.

---

## Phase 1 — Promotion threshold conflict (highest impact, no dependencies)

### Problem
Four different sources state four different consolidation thresholds:

| Source | L2→L3 | L3→L4 | L4→L5 |
|---|---|---|---|
| README.md | 4 recalls / 0.55 importance | 8 / 0.70 | 12 / 0.80 |
| ARCHITECTURE.md | 4 / 0.55 | 8 / 0.70 | 12 / 0.80 |
| `core.py::_promote_memory` (actual running logic) | 2 / 0.40 | 4 / 0.55 | 8 / 0.70 |
| `server.py` dashboard "How" tab copy (hardcoded HTML strings) | 8 / 0.6 | 15 / 0.75 | 25 / 0.85 |

### Fix
1. Decide on one canonical set of thresholds (recommend keeping `core.py`'s current behavior as the source of truth, since that's what's actually running — but this is a judgment call, flag it rather than silently picking one if the docs and code disagree on intent, not just numbers).
2. Define them **once** as named constants at the top of `core.py` (e.g. `_L3_MIN_RECALLS = 2`, `_L3_MIN_IMPORTANCE = 0.40`, etc. for all three tiers) and reference those constants from `_promote_memory` — no inline magic numbers in the function body.
3. Update README.md and ARCHITECTURE.md to match the actual constants.
4. Update the hardcoded dashboard HTML strings in `server.py` (`_build_dashboard` / the "How it works" tab copy) to match — ideally by interpolating the real constants into the HTML at build time rather than hand-typing a fourth copy of the same numbers, so this can't drift again.

### Tests to add (`tests/test_engram.py`)
Write tests against `Engram._promote_memory` directly that assert the **boundary conditions** of whichever thresholds you land on — not just "promotion happens eventually":
- A memory at exactly `min_recalls - 1` / `min_importance` does **not** promote.
- A memory at exactly `min_recalls` / `min_importance` **does** promote to the expected category prefix.
- A memory meeting L4 thresholds but already carrying an `L3_` prefix does not get double-promoted or skip a tier (tests the `if cat.startswith("L3_")...: return` guard).
- A memory with `importance >= 0.8` and `access_count < 2` gets the documented "free promotion to L3" boost — assert the resulting category, not just that the function ran without error.

### Verification
- `pytest tests/test_engram.py -k promote -v` — all new tests pass.
- Manually grep the repo for the old numbers (`4`, `0.55`, `8`, `0.70`, `12`, `0.80`, `8`, `0.6`, `15`, `0.75`, `25`, `0.85` in threshold context) to confirm no stale copy was missed in docs or HTML.

---

## Phase 2 — `/skills/search` misses promoted skills

### Problem
`server.py`'s `/skills/search` handler filters only `result.semantic_hits` for `"skill" in category`. Once a skill is promoted to L3/L4 by consolidation (the exact feature the rest of the system is built around), it moves into `result.procedural_matches` / `result.episodic_matches` instead, which this endpoint never checks. The more a skill is used — which is what triggers promotion — the more likely it silently drops out of search.

### Fix
In the `/skills/search` handler, build `skill_hits` from `result.unified` (which already carries `category` and `layer` for every hit across all layers) instead of only `result.semantic_hits`, filtering on `"skill" in item["category"]` the same way the rest of the codebase already does for cross-layer category matching. Confirm the response shape (`name`, `description`, `score`, `category`) is preserved — check whether `skill_name`/`skill_category` metadata is still available on promoted entries (metadata should survive promotion since `_promote_memory` only updates `category`/`importance`, not the rest of the metadata dict — verify this assumption against the actual ChromaDB update call, don't just assume it).

### Tests to add (`tests/test_server.py`, HTTP-level)
- Store a skill via `/remember` with `category="skill"` and `metadata={"skill_name": "test-skill", "skill_category": "testing"}`.
- Manually force it into a promoted state — either by calling `/recall` enough times to cross the Phase-1 threshold, or (more reliable/faster) by calling `Engram.trigger_consolidation()` after manipulating `access_count` directly via the test's own ChromaDB handle — then call `/skills/search` with a matching query.
- Assert the promoted skill **is** returned, with the correct `name` and `category` fields. This test must fail against the current code (since promoted skills currently vanish from this endpoint) and pass after the fix — confirm that by running it against a git stash of the old handler if you want a sanity check.

### Verification
- `pytest tests/test_server.py -k skills_search -v`
- Confirm by hand: store 5 skills, promote one, call `/skills/search` for it, confirm it's in the response.

---

## Phase 3 — Per-layer token budget isn't actually per-layer

### Problem
`TokenBudget.DEFAULT_ALLOCATION` defines separate percentages for layers 1–5 (10/60/15/10/5%), but `RecallResult.format_for_prompt()` charges every layer-2-through-5 hit against budget index `2` (the 60% pool) via a hardcoded `budget.consume(2, len(label))`. Layers 3/4/5's allocations are defined but never actually constrained at injection time — the "token-aware injection by layer" design goal isn't wired up as documented.

### Fix
In `format_for_prompt`, map each unified item's actual layer (available via `item["layer"]` — `"procedural"`, `"episodic"`, `"reflection"`, or the `"memory (...)"` L2 case) to the correct budget index (2, 3, 4, or 5) before calling `consume()`. You'll need a small mapping from the layer-name string back to the integer layer number — check whether that mapping already exists somewhere (`_CAT_BUCKETS` in `recall()` is close but maps category prefix, not the display string used in `unified`) or whether it needs to be added cleanly in one place rather than duplicated.

### Tests to add (`tests/test_engram.py`)
- Construct a `RecallResult` directly (don't go through a live recall — build the dataclass by hand for a deterministic test) with `unified` containing one item each tagged layer 2, 3, 4, 5, each long enough to be meaningful (e.g. 100 chars), and a small `budget_max_chars` (e.g. 200) so the allocations are tight enough to matter.
- Assert that a layer-5 item is **rejected** when layer 5's tiny 5% allocation is exhausted, even if layer 2's 60% pool still has room — this is the exact bug: today that L5 item would incorrectly succeed by spending from layer 2's budget.
- Assert a layer-2 item that exceeds layer 2's allocation is rejected even when other layers have room (confirms layers don't bleed into each other in either direction).

### Verification
- `pytest tests/test_engram.py -k budget -v`
- Manually call `budget_report()` after a `format_for_prompt()` run and confirm `used_chars` is distributed across multiple layer entries, not concentrated entirely in layer 2's entry.

---

## Phase 4 — Crash and default-mismatch bugs

Two unrelated small bugs, grouped together since both are quick and don't depend on Phases 1–3.

### 4a. Undefined `logger` in `_read_json`
`server.py`'s `_read_json` exception handler calls `logger.warning(...)`, but `logger` is never imported or defined anywhere in the file. Any malformed JSON body to any POST endpoint currently raises `NameError` instead of the intended graceful `{}` fallback.

**Fix:** add `import logging` and `logger = logging.getLogger(__name__)` near the top of `server.py` (module level, not inside the handler), consistent with how a long-running daemon should log rather than silently swallowing every error — don't just remove the log call.

**Test (`tests/test_server.py`):** send a POST to `/remember` with a deliberately malformed body (e.g. raw bytes `b"{not valid json"` with a correct `Content-Length` header) and assert the server responds without raising — i.e. you get back *some* HTTP response (even an error JSON) rather than the connection dying. This test must fail on current code (it'll currently 500/crash with `NameError`) and pass once `logger` exists.

### 4b. `/recall` `min_score` default mismatch
The HTTP handler for `/recall` defaults to `min_score=0.5`; `Engram.recall()` itself defaults to `0.3`, and the README's own documented example uses `0.3`. A client that omits the parameter gets stricter filtering than documented.

**Fix:** change the `/recall` handler's default to `0.3` to match `Engram.recall()` and the documented behavior.

**Test (`tests/test_server.py`):** store a memory with moderate (not strong) semantic relevance to a test query — something you've empirically confirmed scores between 0.3 and 0.5 against that query — call `/recall` with no `min_score` in the body, and assert it's returned. This test must fail at the old 0.5 default and pass at 0.3 — pick content/query pairs you've actually verified land in that score band rather than guessing, since cosine similarity won't always land where intuition suggests.

### Verification
- `pytest tests/test_server.py -k "malformed or min_score" -v`

---

## Phase 5 — Hardcoded path & portability

### Problem
`server.py`'s `/skills/index` handler falls back to a hardcoded `F:/hermes/.hermes/skills` Windows path if the relative path doesn't exist. This breaks on any machine that isn't the original developer's Windows box, including CI.

### Fix
Replace the hardcoded fallback with an environment variable, e.g. `ENGRAM_SKILLS_DIR`, falling back to the existing relative-path logic if unset. Document the new env var in README.md's "Running" section alongside `ENGRAM_DATA_DIR` and `ENGRAM_HOST`.

### Tests to add (`tests/test_server.py`)
- Set `ENGRAM_SKILLS_DIR` to a temp directory containing one fake `SKILL.md`, call `/skills/index`, assert it indexes from that path (not the relative default, not the old hardcoded fallback).
- Confirm the old hardcoded `F:/...` string no longer appears anywhere in `server.py` (`grep -n "F:/hermes" engram/server.py` should return nothing).

**Note:** the same hardcoded-path problem also exists in `scripts/cleanup_engram.py` (`persist_dir="F:/hermes/.hermes/engram_data"`), separate from the `/skills/index` fallback above. Fix that one too — read from `ENGRAM_DATA_DIR` (the env var the rest of the project already uses for this exact purpose, per README.md) instead of hardcoding a second Windows path in a second file. While in that file: its docstring says "Safe — only modifies metadata, no data loss," but Step 2 (`col.delete(ids=[mem_id])` for dedup) does delete records outright. Either make the docstring accurate, or — better — make the script actually safe: add a `--dry-run` flag that reports what would be renamed/deleted without doing it, and require an explicit `--apply` flag to perform deletions for real. A maintenance script that deletes from the only copy of the data, with no backup step anywhere in the project (see Phase 7.3), is exactly the kind of thing that should require an explicit, hard-to-fat-finger opt-in.

### Verification
- `pytest tests/test_server.py -k skills_index -v`
- `grep -rn "F:/hermes" engram/ scripts/` returns no results.
- Running `python scripts/cleanup_engram.py` with no flags performs no deletions and only reports what it would do.

---

## Phase 6 — Best practices (do last, lower risk/impact than Phases 1–5)

These don't fix user-facing bugs but reduce future risk. Do these only after Phases 1–5 are verified, since some touch the same files.

1. **Cache `EmbeddingModel.dimensions`.** Currently runs a live embedding inference on every access just to read a constant. Compute it once on first model load and cache on the instance.
   - Test: mock or count calls to the underlying `encode`/embed call; assert accessing `.dimensions` twice only triggers one actual embedding computation.

2. **Batch `increment_access_count`.** Currently does one ChromaDB `get` + `update` round trip per hit, in a loop, on every recall — O(2N) I/O calls per query. Refactor to a single batched read + single batched update where ChromaDB's API allows it (check `collection.get(ids=[...])` and `collection.update(ids=[...], metadatas=[...])` both accept lists — they do, per existing usage elsewhere in the file).
   - Test: assert that recalling with N hits results in a bounded, small number of ChromaDB calls regardless of N (e.g. mock the collection and assert call count, or just assert correctness after the refactor — all N access counts incremented correctly in one batch — plus a timing-based sanity check isn't required, but a correctness one is).

3. **Add minimal but real tests for consolidation's decay/purge path.** `_run_consolidation_tick`'s decay and purge logic currently has zero test coverage.
   - Test: create a memory, manually backdate its `created_at` metadata past `_DECAY_DAYS`, set `access_count` below the no-decay threshold, run `trigger_consolidation()`, and assert importance actually decreased. Separately, backdate one far enough and low enough in importance that it should cross `_MIN_IMPORTANCE` and assert it was actually purged (count decreases).

4. **Don't set attributes on the stdlib `HTTPServer` class itself.** `EngramServer.start()` currently does `HTTPServer._start_time = self._start_time`, mutating the built-in class. Store it on the `_Handler` class or the `EngramServer` instance instead.
   - Test: not strictly testable behaviorally, but add an assertion in an existing server-startup test that `HTTPServer` (the imported stdlib class, fresh) has no `_start_time` attribute after a server starts and stops — guards against regression.

### Verification for Phase 6
- Full suite: `pytest -v` — confirm total pass count increased by the number of new tests across all six phases, and that no previously-passing test now fails.
- Re-read README.md and ARCHITECTURE.md once more after all phases — confirm every documented number/path/filename actually matches the code (this is the same check that started this whole audit; close the loop on it before calling the work done).

---

## Phase 7 — Robustness & usefulness improvements

These go beyond fixing what's broken — they make the system more trustworthy to operate and more useful for an agent to reason about its own memory. Do this last; it's additive, lower-urgency than Phases 1–6, and touches a wider surface.

### 7.1 `/health` should actually check health, not just report "ok"
**Problem:** `/health` unconditionally returns `"status": "ok"` regardless of whether the embedding model loaded successfully, whether ChromaDB is reachable, or whether the consolidation thread is still alive. `stats()` already tracks `consolidation.thread_alive` but `/health` doesn't surface it. A crashed consolidation thread or a dead embedding model currently looks identical to a fully healthy server from the outside.

**Fix:** have `/health` actually probe: confirm `self.engram._semantic.collection.count()` succeeds (catches a broken ChromaDB connection), include `consolidation.thread_alive` in the response, and report `"status": "degraded"` (not `"ok"`) if either check fails, with a `"checks"` object showing which one. Keep the response fast — these are cheap local checks, not a full collection scan.

**Test:** kill the consolidation thread directly in a test (`engram._consolidation_thread` — stop it without calling `close()`), call `/health`, assert `status` is no longer `"ok"` and the response indicates which check failed. This test must fail against current code (which would still report `"ok"`) and pass after the fix.

### 7.2 Surface dedup-merge vs. new-write in `/remember`'s response
**Problem:** `/remember` always returns `{"status": "stored", ...}`, whether the content was actually stored as new or silently merged into an existing memory via the ≥85% similarity dedup check. Per ARCHITECTURE.md, the agent dual-writes to both Hermes' own memory and Engram on an "Engram-first mandate" — but it currently has no way to tell, from the response alone, whether what it just wrote was novel or got absorbed into something that already existed. That distinction matters for an agent trying to track what it actually knows.

**Fix:** have `Engram.remember()` return a small result object (or the server layer wrap it) distinguishing the two cases — e.g. `{"status": "stored", "memory_id": "...", "merged": false}` for a new memory vs. `{"status": "merged", "memory_id": "<existing id>", "merged": true, "new_importance": 0.73}` when the dedup path fires. This is a response-shape change — check `dashboard/src/api.ts` and any other caller for whether they pattern-match on `status == "stored"` before changing it, and update them if so.

**Test:** call `/remember` twice with near-identical content (above the dedup threshold), assert the second response has `merged: true` and the same `memory_id` as the first. Call it again with genuinely distinct content, assert `merged: false`. Both branches need their own assertion — don't just test one and assume the other works.

### 7.3 Add a backup/export endpoint and CLI command
**Problem:** there is currently no way to export or back up Engram's memory store anywhere in the project. The only existing maintenance tool (`scripts/cleanup_engram.py`) deletes records and has no corresponding backup step. ChromaDB persistence to disk protects against process crashes, but not against a bad consolidation tick, a bug in a future migration script, or simple human error — all of which currently have no recovery path.

**Fix:** add a `GET /export` endpoint (and a thin CLI wrapper, e.g. `python -m engram.export > backup.json`) that dumps every memory's `id`, `content`, full `metadata`, and `category` as JSON — everything needed to fully reconstruct the store via `batch_remember()` (already exists in `semantic_index.py`) on a fresh ChromaDB instance. Pair it with a matching `import` path (CLI is fine; doesn't need to be an HTTP endpoint) that re-embeds and re-inserts from an exported file, so this is a real round-trip, not just a one-way dump nobody can restore from.

**Test:** export a populated test store, clear it (`Engram.clear()`), re-import from the export, assert `count()` matches the original and a spot-checked memory's `content`/`category`/`importance` survived the round trip exactly.

### 7.4 Fix `/episodes/list`, `/reflections/list`, `/procedures/list` to actually list, not semantically search
**Problem:** all three "list" endpoints are implemented as a semantic search against a hardcoded placeholder query string (e.g. `"session conversation episode event"`) with `min_score=0.0` and `limit=200`. This works by coincidence for small collections, but it's not a true unfiltered list — ChromaDB's `n_results` truncation combined with ranking-by-similarity-to-a-made-up-query means that once a layer has more entries than the limit, which ones get silently dropped depends on their similarity to a placeholder string that has nothing to do with the user's actual intent ("show me everything"). A true list operation shouldn't depend on a query at all.

**Fix:** add a real unfiltered listing path — either a `category_filter`-only query in `SemanticIndex` that doesn't require an embedding/similarity step (the `collection.get(where=...)` pattern already used in `_run_consolidation_tick` and `list_categories` is the right shape — reuse it instead of `collection.query`), or a dedicated `list_by_category()` method on `SemanticIndex`. Wire all three endpoints to that instead of a fake query string.

**Test:** store more than 200 episodes (or temporarily lower an internal limit constant for the test, whichever is faster), call `/episodes/list`, and assert the count matches the true total rather than being silently truncated or sampled by similarity. This is the key regression case — a test with under-200 episodes wouldn't catch this bug at all, so don't write one that does.

### 7.5 Make `/recall` explain its ranking, not just return scores
**Problem:** the unified recall response includes each hit's `score` and `importance`, but not the `combined_score` that's actually used to rank and truncate the list (`score * 0.6 + importance * 0.4`, computed in `core.py` but dropped before the response is built). An agent — or Jeremy, debugging from the dashboard — currently has to reverse-engineer why one memory outranked another with a higher raw similarity score.

**Fix:** include `combined_score` in each unified item in the `/recall` response (it's already computed; just stop discarding it before serialization). This is a small, low-risk addition — no behavior change, just don't throw away information that's already there.

**Test:** call `/recall`, assert every item in `unified` has a `combined_score` key, and assert the list is actually sorted by it (descending) — pinning down the contract, not just its presence.

### Verification for Phase 7
- `pytest -v` — full suite green, including all new 7.1–7.5 tests.
- Manually run the new export/import round-trip against a real (not just test) `ENGRAM_DATA_DIR` copy once, by hand, before trusting it — this is exactly the kind of feature that's worse than useless if it silently doesn't round-trip correctly.
- Update README.md's API table to document `/export` and the corrected `/health` response shape — don't let this phase introduce its own version of the doc-drift problem Phase 1 just fixed.
