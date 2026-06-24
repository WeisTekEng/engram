#!/usr/bin/env python3
"""Engram cleanup: normalize category prefixes + deduplicate skills.

WARNING: Step 2 deletes duplicate records. Use --apply to execute changes,
or omit it (default: --dry-run) to preview only.
"""

import sys, os, json, hashlib

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engram.core import Engram

# ── CLI flags ──
DRY_RUN = "--dry-run" in sys.argv or "--apply" not in sys.argv
APPLY = "--apply" in sys.argv

# ── Use ENGRAM_DATA_DIR env var, with Windows fallback ──
data_dir = os.environ.get("ENGRAM_DATA_DIR", "")
if not data_dir:
    # Fallback: try default location relative to this script
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", ".hermes", "engram_data")
    if os.path.isdir(default):
        data_dir = default
    else:
        print("ERROR: ENGRAM_DATA_DIR not set and default path not found.")
        print("  Set with: set ENGRAM_DATA_DIR=F:/hermes/.hermes/engram_data")
        sys.exit(1)

if DRY_RUN:
    print("=== DRY RUN (no changes will be made) ===")
    print(f"  Use --apply to execute changes.\n")

print(f"Using data dir: {data_dir}")

engram = Engram(
    persist_dir=data_dir,
    budget_max_chars=2000,
    auto_bootstrap=False,
)

sem = engram._semantic
col = sem.collection

# Get all data
all_data = col.get(include=["metadatas", "documents"])
total = len(all_data["ids"]) if all_data["ids"] else 0
print(f"Total memories: {total}")

# ── Step 1: Normalize category prefixes ──
renames = 0
category_renames = {
    "layer3_procedural": "L3_procedural_procedural",
    "layer4_episodic": "L4_episodic_episodic",
    "layer5_reflection": "L5_reflection_reflection",
}

for i, mem_id in enumerate(all_data["ids"]):
    meta = dict(all_data["metadatas"][i]) if all_data["metadatas"] else {}
    cat = meta.get("category", "")
    if cat in category_renames:
        new_cat = category_renames[cat]
        if APPLY:
            meta["category"] = new_cat
            col.update(ids=[mem_id], metadatas=[meta])
        renames += 1
        if renames <= 10:
            print(f"  {'[DRY RUN] ' if DRY_RUN else ''}{cat} → {new_cat}")

print(f"Category renames: {renames}")

# ── Step 2: Deduplicate by content_hash (DELETES records when --apply) ──
seen_hashes = {}
dupes_removed = 0
dup_examples = []

for i, mem_id in enumerate(all_data["ids"]):
    meta = dict(all_data["metadatas"][i]) if all_data["metadatas"] else {}
    doc = all_data["documents"][i] if all_data["documents"] else ""

    content_hash = meta.get("content_hash") or hashlib.md5(doc.encode()).hexdigest()
    cat = meta.get("category", "general")
    key = f"{cat}:{content_hash}"

    if key in seen_hashes:
        dupes_removed += 1
        if len(dup_examples) < 5:
            dup_examples.append((mem_id, doc[:80]))
        if APPLY:
            col.delete(ids=[mem_id])
    else:
        seen_hashes[key] = mem_id

if dup_examples:
    print(f"\nDuplicates found: {dupes_removed}")
    for mid, preview in dup_examples:
        print(f"  {'[DRY RUN]' if DRY_RUN else '[WOULD DELETE]'} {mid[:12]}... \"{preview}\"")
if DRY_RUN and dupes_removed > 0:
    print("  (use --apply to actually remove these)")

# ── Step 3: Flag orphan skills ──
orphan_skills = 0
for i, mem_id in enumerate(all_data["ids"]):
    meta = dict(all_data["metadatas"][i]) if all_data["metadatas"] else {}
    if meta.get("category") == "skill" and not meta.get("skill_name"):
        orphan_skills += 1

print(f"Orphan skills (no name): {orphan_skills}")
if orphan_skills > 0 and not DRY_RUN:
    print("  (--apply only affects steps 1-2; orphan skills need re-index)")
elif orphan_skills > 0:
    print("  (run POST /skills/index to re-index; orphan skills are informational only)")

# ── Step 4: Trigger consolidation ──
if APPLY:
    result = engram.trigger_consolidation()
    print(f"Consolidation: {json.dumps(result)}")
else:
    print("Consolidation: skipped (DRY RUN — use --apply to run)")

# ── Final stats ──
if not DRY_RUN:
    stats = engram.stats()
    print(f"\nFinal stats:")
    print(f"  L1 hot: {stats['hot_cache_size']}")
    print(f"  L2 semantic: {stats['semantic_index']['total_memories']}")
    print(f"  Layers: {stats['layers']}")
    print(f"  Consolidation: {stats['consolidation']}")

engram.close()
print("\nDone.")
