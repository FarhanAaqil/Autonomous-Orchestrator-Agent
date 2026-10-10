# Autonomous Orchestrator Agent — Operations Runbook

**Version**: `1.0.0`  
**Target Environment**: Production / Local Daemon  
**Runtime**: Python 3.11+ / Node.js 20+  

---

## 1. Starting the Services

### Core API & Web Control Plane
Start the FastAPI server on port 8000:
```bash
python -m uvicorn orchestrator_core.main:app --host 127.0.0.1 --port 8000
```
- Access Swagger UI API docs: [`http://127.0.0.1:8000/docs`](http://127.0.0.1:8000/docs)
- Access Executive Control Plane Dashboard: [`http://127.0.0.1:8000/`](http://127.0.0.1:8000/)

### Background Autonomy Worker
To run dedicated background worker processes claiming and running queued jobs:
```bash
python -m orchestrator_core.jobs.worker
```

### Browser Sandbox (Optional Container)
To run the Playwright browser sandbox container:
```bash
docker build -t orchestrator-browser-sandbox docker/browser_sandbox
docker run -p 8888:8888 --read-only --tmpfs /tmp --cpus="1.0" --memory="1024m" orchestrator-browser-sandbox
```

---

## 2. Emergency Operations

### Activating the Kill Switch
If an agent acts unexpectedly or an emergency freeze is required:
- **Via Web Dashboard**: Open the **Settings** view and toggle **Emergency Kill Switch** to `ON`.
- **Via REST API**:
  ```bash
  curl -X POST http://127.0.0.1:8000/system/kill-switch -H "Content-Type: application/json" -d '{"on": true}'
  ```
- **Effect**: All queued and running agent loops abort within 1 step and transition to `cancelled`. Workers immediately pause job claims.

### Deactivating the Kill Switch
```bash
curl -X POST http://127.0.0.1:8000/system/kill-switch -H "Content-Type: application/json" -d '{"on": false}'
```

### Inspecting and Resetting Router Circuit Breaker
- Check circuit health:
  ```bash
  curl http://127.0.0.1:8000/system/circuit
  ```
- Manually reset an open circuit breaker:
  ```bash
  curl -X POST http://127.0.0.1:8000/system/circuit/reset
  ```

---

## 3. Disaster Recovery & Backups

### Creating an Automated Snapshot
```bash
python scripts/backup_restore.py snapshot --dest backups/snapshot_latest
```

### Restoring from Backup
```bash
python scripts/backup_restore.py restore-db --backup backups/snapshot_latest/aaqil.db --target aaqil.db
python scripts/backup_restore.py restore-chroma --archive backups/snapshot_latest/chroma.tar.gz --target chroma_db
```

---

## 4. Test Suite & Quality Gates

Run full test suite:
```bash
pytest -m "not real_llm" -v
```

Run static lint checks:
```bash
ruff check orchestrator_core/ tests/
```

Run Router Evaluation Gate (100% Frozen Split):
```bash
python eval/run_eval.py --dry-run --split test --ci-gate --no-save
```
