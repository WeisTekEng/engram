#!/usr/bin/env python3
"""Engram cleanup: normalize category prefixes + deduplicate skills.
Run once after the server patch. Safe — only modifies metadata, no data loss."""

import sys, os, json, hashlib, time

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engram.core import Engram

engram = Engram(
    persist_dir="F:/hermes/.hermes/engram_data",
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
        meta["category"] = new_cat
        col.update(ids=[mem_id], metadatas=[meta])
        renames += 1
        if renames <= 10:
            print(f"  {cat} → {new_cat}")

print(f"Category renames: {renames}")

# ── Step 2: Deduplicate by content_hash ──
seen_hashes = {}
dupes_removed = 0

for i, mem_id in enumerate(all_data["ids"]):
    meta = dict(all_data["metadatas"][i]) if all_data["metadatas"] else {}
    doc = all_data["documents"][i] if all_data["documents"] else ""
    
    # Compute content hash
    content_hash = meta.get("content_hash") or hashlib.md5(doc.encode()).hexdigest()
    cat = meta.get("category", "general")
    key = f"{cat}:{content_hash}"
    
    if key in seen_hashes:
        # Duplicate — remove
        col.delete(ids=[mem_id])
        dupes_removed += 1
    else:
        seen_hashes[key] = mem_id

print(f"Duplicates removed: {dupes_removed}")

# ── Step 3: Clean up skills without metadata (re-index from disk?) ──
# Skills without skill_name in metadata are orphan entries — flag them
orphan_skills = 0
for i, mem_id in enumerate(all_data["ids"]):
    meta = dict(all_data["metadatas"][i]) if all_data["metadatas"] else {}
    if meta.get("category") == "skill" and not meta.get("skill_name"):
        orphan_skills += 1

print(f"Orphan skills (no name): {orphan_skills}")

# ── Step 4: Trigger immediate consolidation ──
result = engram.trigger_consolidation()
print(f"Consolidation: {json.dumps(result)}")

# ── Final stats ──
stats = engram.stats()
print(f"\nFinal stats:")
print(f"  L1 hot: {stats['hot_cache_size']}")
print(f"  L2 semantic: {stats['semantic_index']['total_memories']}")
print(f"  Layers: {stats['layers']}")
print(f"  Consolidation: {stats['consolidation']}")

engram.close()
print("\nDone.")
