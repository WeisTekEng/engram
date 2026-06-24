# Engram Windows Service

Engram runs as a Windows service via NSSM (Non-Sucking Service Manager). If the process dies, Windows restarts it automatically.

## Service Details

| Field | Value |
|-------|-------|
| Name | `Engram` |
| Binary | `F:\hermes\.hermes\hermes-agent\venv\Scripts\python.exe` |
| Arguments | `F:\hermes\engram_memory\engram\server_daemon.py` |
| Directory | `F:\hermes\engram_memory` |
| Startup | Automatic (starts on boot) |
| Environment | `ENGRAM_DATA_DIR=F:\hermes\.hermes\engram_data ENGRAM_HOST=0.0.0.0` |
| Logs | `F:\hermes\.hermes\engram_service.log` |
| Port | 8092 |

## Commands

```bash
# Status
F:\hermes\nssm.exe status Engram

# Start / Stop / Restart
F:\hermes\nssm.exe start Engram
F:\hermes\nssm.exe stop Engram
F:\hermes\nssm.exe restart Engram

# View configuration
F:\hermes\nssm.exe dump Engram

# Remove service (if needed)
F:\hermes\nssm.exe remove Engram confirm
```

## Health Check

```bash
curl http://127.0.0.1:8092/health
# Expect: {"status": "ok", ...}
```

## Recovery

NSSM is configured with default recovery: if the process exits, it restarts. For catastrophic failures (port conflict, corrupt ChromaDB), check `F:\hermes\.hermes\engram_service.log`.

## Installation

Service was installed on 2026-06-23 with:
```bash
F:\hermes\nssm.exe install Engram \
  F:\hermes\.hermes\hermes-agent\venv\Scripts\python.exe \
  F:\hermes\engram_memory\engram\server_daemon.py

F:\hermes\nssm.exe set Engram AppDirectory F:\hermes\engram_memory
F:\hermes\nssm.exe set Engram AppEnvironmentExtra "ENGRAM_DATA_DIR=F:\hermes\.hermes\engram_data ENGRAM_HOST=0.0.0.0"
F:\hermes\nssm.exe set Engram AppStdout F:\hermes\.hermes\engram_service.log
F:\hermes\nssm.exe set Engram AppStderr F:\hermes\.hermes\engram_service.log
F:\hermes\nssm.exe set Engram Start SERVICE_AUTO_START
F:\hermes\nssm.exe set Engram Description "Engram Semantic Memory Server (5-layer ChromaDB)"
```
