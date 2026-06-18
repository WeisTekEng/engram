#!/usr/bin/env python3
"""Launch the Engram memory server.

Usage:
    python -m engram.server_daemon
    # or directly:
    python engram/server_daemon.py
"""

import os
import sys
import signal

# Add parent to path so 'import engram' works
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engram.server import EngramServer


def main():
    persist_dir = os.environ.get(
        "ENGRAM_DATA_DIR",
        os.path.expanduser("~/.hermes/engram_data")
    )
    host = os.environ.get("ENGRAM_HOST", "127.0.0.1")
    port = int(os.environ.get("ENGRAM_PORT", "8092"))

    print(f"[Engram] Starting server on {host}:{port}")
    print(f"[Engram] Data: {persist_dir}")

    server = EngramServer(
        persist_dir=persist_dir,
        host=host,
        port=port,
        auto_bootstrap=True,
    )

    # Handle graceful shutdown
    def shutdown(signum, frame):
        print("\n[Engram] Shutting down...")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"[Engram] Dashboard: http://{host}:{port}/dashboard")
    print(f"[Engram] API: http://{host}:{port}/health")
    print(f"[Engram] Ready.")

    server.start()


if __name__ == "__main__":
    main()
