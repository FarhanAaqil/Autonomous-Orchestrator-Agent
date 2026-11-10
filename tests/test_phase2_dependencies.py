from orchestrator_core.jobs.service import JobService
from orchestrator_core.jobs.dependencies import reconcile
from orchestrator_core.runner.loop import run_job


def test_approval_result_resumes_once(db):
    job = JobService.create_job('email_agent', 'Prepare a message', db)
    run_job(job, db, llm_client=lambda _: '{"action":"propose","action_input":{"action_type":"send_email","payload":{"to":"test@example.com","subject":"Test","body":"Test"}}}')
    approval = db.execute('SELECT id FROM approvals').fetchone()[0]
    db.execute("UPDATE approvals SET status='confirmed' WHERE id=?", (approval,))
    db.commit()
    assert reconcile(db) == [job.id]
    assert reconcile(db) == []
    assert JobService.get_job(job.id, db).status == 'queued'
    assert sum(step.name == 'dependency_result' for step in JobService.get_steps(job.id, db)) == 1


def test_child_failure_terminates_waiting_parent(db):
    job = JobService.create_job('general_chat', 'Delegate work', db)
    run_job(job, db, llm_client=lambda _: '{"action":"handoff","action_input":{"target_agent":"general_chat","sub_goal":"Child work"}}')
    db.execute("UPDATE jobs SET status='failed',error='provider failed' WHERE parent_job_id=?", (job.id,))
    db.commit()
    assert reconcile(db) == [job.id]
    assert JobService.get_job(job.id, db).status == 'failed'
