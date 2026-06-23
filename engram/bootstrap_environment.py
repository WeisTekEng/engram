#!/usr/bin/env python3
"""Engram smart bootstrap — pre-loads high-value environment facts into L2.

Run at first startup. Safe to re-run — Engram's auto-dedup (0.85 threshold)
prevents duplicates and only boosts existing importance.

Usage: python bootstrap_environment.py
"""

import json, time, urllib.request, urllib.error

API = "http://127.0.0.1:8092"
HEADERS = {"Content-Type": "application/json"}

def store(content, category, importance=0.9):
    """Store a fact, safe against duplicates (engram auto-dedups)."""
    try:
        body = json.dumps({
            "content": content,
            "layer": 2,
            "category": category,
            "importance": importance,
            "metadata": {"source": "engram-bootstrap"},
        }).encode()
        req = urllib.request.Request(f"{API}/remember", data=body, headers=HEADERS)
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        return result.get("memory_id", "?")
    except Exception as e:
        print(f"  FAIL: {e}")
        return None

FACTS = [
    # Machine identity
    ("Host: DESKTOP-H0J0NTE running Windows 10 with Git Bash/MSYS terminal. User home: C:\\WINDOWS\\system32\\config\\systemprofile. Tailscale IP: 100.104.70.8",
     "environment"),

    # Disk layout
    ("Disk layout: C: drive is 111GB and perpetually near-full (system files). F: drive is 466GB with 459GB free. ALL installs, caches, and data go to F: at F:\\hermes\\. Never install to C:.",
     "environment"),

    # Android build
    ("Android build environment: JAVA_HOME=F:\\hermes\\.cache\\android_build\\jdk21\\jdk-21.0.9+10 (OpenJDK 21 Temurin). ANDROID_HOME=F:\\hermes\\.cache\\android_build\\android-sdk. GRADLE_USER_HOME=F:\\hermes\\.cache\\gradle. All builds use F: drive only. C: has no space for Gradle caches.",
     "environment"),

    # Python
    ("Python is uv-managed. Hermes venv at F:\\hermes\\.hermes\\hermes-agent\\venv with pyvenv.cfg offloaded stdlib. Stdlib offload: F:\\hermes\\.offload\\uv-roaming\\python\\cpython-3.11-windows-x86_64-none. Never set PYTHONHOME — the venv pyvenv.cfg handles it. Never move uv dirs while Python processes run (DLL locks).",
     "environment"),

    # Services
    ("Active services on DESKTOP-H0JNTE (Tailscale 100.104.70.8): 5174=Buckets SPA+landing, 5177=Buckets sync (FastAPI), 8092=Engram (5-layer ChromaDB memory+dashboard), 9119=Hermes Dashboard (jeremy/hermes-dash-2026), 8644=Hermes webhook (127.0.0.1), 443=Caddy/Tailscale Funnel",
     "environment"),

    # Hermes gateway
    ("Hermes gateway startup from PowerShell: $env:HERMES_HOME = 'F:\\hermes\\.hermes'; F:\\hermes\\.hermes\\hermes-agent\\venv\\Scripts\\python.exe -m hermes_cli.main gateway run",
     "environment"),

    # GitHub
    ("GitHub: user=WeisTekEng, repos: Buckets, Engram. Token base64 at F:\\hermes\\.hermes\\.github_token_b64. Push via REST API (git 2.47+ Bearer/Basic mismatch). Never expose token in shell.",
     "environment"),

    # Upgrade safety
    ("Upgrade safety rule: Never patch hermes-agent internals (tools/, agent/, hermes_cli/). Hermes updates silently overwrite these. Use env vars (setx) and config.yaml for persistent config. All custom code goes in F:\\hermes\\engram_memory\\ (safe from updates).",
     "lesson_learned"),

    # Engram
    ("Engram is standalone 5-layer memory: L1 hot cache, L2 semantic ChromaDB, L3 procedural, L4 episodic, L5 reflective. Auto-dedup, auto-consolidation (30min, decay+promote). All self-contained — no cron dependency. Server at F:\\hermes\\engram_memory\\engram\\server.py, data at F:\\hermes\\.hermes\\engram_data\\.",
     "infrastructure"),

    # Buckets project
    ("Buckets project: React/Vite/TypeScript Capacitor Android APK at F:\\hermes\\buckets. Self-contained APK (bundled dist/, sync-only network via :5177). 97 vitest tests pass. Build chain: vite build → cap sync android → gradle assembleDebug. emptyOutDir:false preserves dist/. .capacitorignore excludes *.apk. GitHub branch: feat/react-refactor",
     "infrastructure"),
]

print("=== Engram Smart Bootstrap ===")
stored = 0
for content, category in FACTS:
    mid = store(content, category)
    if mid:
        stored += 1
        print(f"  ✓ [{category}] {content[:60]}...")
    time.sleep(0.3)

print(f"\nBootstrap complete: {stored}/{len(FACTS)} facts stored")
print("Engram auto-dedup prevents duplicates on re-runs.")
