"""Durable router evaluation submissions and database-backed result history."""
import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from orchestrator_core.storage.db import get_db_connection

router = APIRouter(prefix='/router', tags=['Eval'])
_DATASET_PATH = Path(__file__).resolve().parents[2] / 'eval' / 'fixed_set.json'


def evaluate(eval_id, db):
    from eval.run_eval import run_classification, compute_metrics, prompt_hash
    from orchestrator_core.config import get_settings
    from orchestrator_core.jobs.leases import require_lease
    from orchestrator_core.storage.transactions import transaction
    results = run_classification(json.loads(_DATASET_PATH.read_text(encoding='utf-8')))
    metrics = compute_metrics(results)
    with transaction(db):
        require_lease(db)
        db.execute('INSERT INTO router_eval_runs (eval_id,total_commands,accuracy,per_agent_json,confusion_matrix_json,model_name,prompt_hash) VALUES (?,?,?,?,?,?,?)',
                   (eval_id, metrics['total'], metrics['accuracy'], json.dumps(metrics['per_agent']), json.dumps(metrics['confusion_matrix']), get_settings().router_model, prompt_hash()))
    return {'eval_id': eval_id, 'accuracy': metrics['accuracy'], 'total': metrics['total']}


@router.post('/eval', status_code=202)
def run_eval(db=Depends(get_db_connection)):
    if not _DATASET_PATH.is_file():
        raise HTTPException(503, 'Evaluation resources are unavailable in this deployment')
    from orchestrator_core.jobs.background import enqueue
    job_id = enqueue(db, 'evaluation', {})
    return {'eval_id': job_id, 'job_id': job_id, 'status': 'queued'}


@router.get('/eval')
def get_latest_eval(db=Depends(get_db_connection)):
    row = db.execute('SELECT * FROM router_eval_runs ORDER BY run_at DESC LIMIT 1').fetchone()
    return dict(row) if row else {'message': 'No eval runs found'}


@router.get('/evals')
def list_evals(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db=Depends(get_db_connection)):
    rows = db.execute('SELECT * FROM router_eval_runs ORDER BY run_at DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()
    return {'runs': [dict(row) for row in rows], 'total': db.execute('SELECT COUNT(*) FROM router_eval_runs').fetchone()[0]}
