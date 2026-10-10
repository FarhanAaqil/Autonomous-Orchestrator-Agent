# Disaster Recovery & Backup Runbook

**Service**: Autonomous Orchestrator Agent v1.0.0  
**Data Stores**:
1. SQLite: Primary relational store (`aaqil.db`) with WAL mode
2. ChromaDB: Vector embeddings store (`chroma_db/`)

---

## 1. Disaster Recovery Objectives

| Metric | Target | Description |
| :--- | :--- | :--- |
| **RPO (Recovery Point Objective)** | **≤ 1 hour** | Maximum allowable data loss in the event of hardware or storage failure. Achieved via hourly automated snapshots. |
| **RTO (Recovery Time Objective)** | **< 30 seconds** | Time required to restore the full system from verified backup to operational status. |
| **Backup Atomicity** | **100% Non-blocking** | Uses SQLite `backup()` API; zero disruption to active concurrent readers or writers in WAL mode. |
| **Integrity Guarantee** | **SHA-256 + PRAGMA** | Backups are validated with `PRAGMA integrity_check;` before acceptance and verified via SHA-256 manifest. |

---

## 2. Automated Snapshot Architecture

Every full system snapshot contains:
- `aaqil.db`: Online SQLite point-in-time snapshot.
- `chroma.tar.gz`: Vector database embedding index snapshot.
- `manifest.json`: Verification manifest containing ISO-8601 timestamp, byte sizes, and cryptographic SHA-256 hashes.

---

## 3. Operations Runbook

### A. Taking an Immediate Snapshot
Run the disaster recovery CLI:
```bash
python scripts/backup_restore.py snapshot --dest backups/snapshot_manual
```

Sample output:
```text
[OK] Full system snapshot created at: .../backups/snapshot_manual
     SQLite SHA256: 4a2f8...
     Chroma SHA256: e891d...
```

### B. Verifying Backup Integrity
To verify that a backup file has not suffered bit rot or corruption:
```bash
python scripts/backup_restore.py verify --file backups/snapshot_manual/aaqil.db
```

### C. Restoring the SQLite Database
To restore from a backup:
```bash
# Gracefully stop the service if running
python scripts/backup_restore.py restore-db --backup backups/snapshot_manual/aaqil.db --target aaqil.db
```

### D. Restoring ChromaDB
```bash
python scripts/backup_restore.py restore-chroma --archive backups/snapshot_manual/chroma.tar.gz --target chroma_db
```

---

## 4. Disaster Recovery Validation Drill Results

The backup and recovery procedures were validated in automated test suite `tests/test_backup_restore.py`:
- Online backup created without write locks: **PASSED**
- Point-in-time recovery restoring mutated state: **PASSED**
- Rejection of corrupted SQLite files before application: **PASSED**
- ChromaDB roundtrip extraction and index restoration: **PASSED**
- Coordinated snapshot creation with SHA-256 manifest: **PASSED**
