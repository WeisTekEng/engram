"""Engram export/import — round-trip backup and restore.

Export:  GET /export            (or: python -m engram.export export > backup.json)
Import:  python -m engram.export import backup.json           (dry-run preview)
         python -m engram.export import backup.json --apply   (actual import)

Import defaults to dry-run mode — pass --apply to actually clear and import.
"""

import json
import os
import sys


def export_memories(engram_instance_or_path: str = None) -> list:
    """Export all memories from an Engram instance or data dir as JSON-serializable list."""
    from engram import Engram

    if engram_instance_or_path is None:
        eng = Engram(auto_bootstrap=False)
    elif isinstance(engram_instance_or_path, str):
        eng = Engram(persist_dir=engram_instance_or_path, auto_bootstrap=False)
    else:
        eng = engram_instance_or_path

    all_data = eng._semantic.collection.get(include=["metadatas", "documents"])
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
    return memories


def import_memories(memories: list, target_dir: str = None, confirm: bool = False):
    """Import memories from an export list into a fresh Engram instance.

    When confirm=False (default), performs a dry-run preview only:
    reports what would happen without modifying anything on disk.
    Pass confirm=True to actually clear and import.

    Returns dict with 'imported' count (real or would-be) and 'dry_run' flag.
    """
    from engram import Engram

    eng = Engram(persist_dir=target_dir or "~/.hermes/engram", auto_bootstrap=False)

    existing_count = eng._semantic.count()

    if not confirm:
        return {
            "dry_run": True,
            "would_import": len(memories),
            "would_clear": existing_count,
            "existing_memories": existing_count,
        }

    # Clear existing data (only with confirm=True)
    eng.clear()

    # Use batch_remember for efficiency
    batch = []
    for mem in memories:
        batch.append({
            "content": mem["content"],
            "category": mem.get("category", "general"),
            "importance": mem.get("importance", 0.5),
            "metadata": {
                "created_at": mem.get("created_at", ""),
                "access_count": int(mem.get("access_count", 0)),
                **mem.get("metadata", {}),
            },
        })

    if batch:
        ids = eng._semantic.batch_remember(batch)
        for mem, mid in zip(memories, ids):
            eng._push_hot(mem["content"])
        return {"dry_run": False, "imported": len(ids)}
    return {"dry_run": False, "imported": 0}


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m engram.export <command> [args]")
        print("  export [data_dir]       — Export all memories as JSON to stdout")
        print("  import <file.json> [target_dir] [--apply] — Import from JSON file")
        print("  import defaults to dry-run preview; pass --apply to commit")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "export":
        data_dir = sys.argv[2] if len(sys.argv) > 2 else None
        memories = export_memories(data_dir)
        print(json.dumps({
            "exported_at": __import__("datetime").datetime.now().isoformat(),
            "total": len(memories),
            "memories": memories,
        }, indent=2))

    elif cmd == "import":
        if len(sys.argv) < 3:
            print("Usage: python -m engram.export import <file.json> [target_dir] [--apply]")
            sys.exit(1)
        filepath = sys.argv[2]
        # Check for --apply anywhere after positionals
        confirm = "--apply" in sys.argv
        target_dir = None
        for arg in sys.argv[3:]:
            if arg != "--apply":
                target_dir = arg

        with open(filepath) as f:
            data = json.load(f)

        memories = data.get("memories", data) if isinstance(data, dict) else data
        result = import_memories(memories, target_dir, confirm=confirm)
        if result["dry_run"]:
            print(f"DRY-RUN: would clear {result['would_clear']} existing memories "
                  f"and import {result['would_import']} from {filepath}")
            print("Pass --apply to actually import.")
        else:
            print(f"Imported {result['imported']} memories.")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
