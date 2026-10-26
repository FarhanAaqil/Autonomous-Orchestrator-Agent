"""Capture job changes in the same transaction as durable events."""
def install(db):
    pg = getattr(db, 'dialect', None) == 'postgresql'
    identity = 'BIGSERIAL PRIMARY KEY' if pg else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    db.execute(f'CREATE TABLE job_events (id {identity}, event TEXT NOT NULL, data_json TEXT NOT NULL)')
    if pg:
        db.execute("""CREATE FUNCTION capture_job_event() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE kind TEXT; payload TEXT;
        BEGIN
          IF TG_TABLE_NAME='job_steps' THEN
            kind := 'job.step';
            payload := json_build_object('job_id',NEW.job_id,'step_idx',NEW.idx,'kind',NEW.kind)::text;
          ELSE
            IF TG_OP='UPDATE' AND OLD.status=NEW.status THEN RETURN NEW; END IF;
            kind := CASE WHEN TG_OP='INSERT' THEN 'job.created' WHEN NEW.status='running' THEN 'job.claimed' ELSE 'job.status_changed' END;
            payload := json_build_object('job_id',NEW.id,'status',NEW.status)::text;
          END IF;
          PERFORM pg_advisory_xact_lock(74201903);
          INSERT INTO job_events(event,data_json) VALUES(kind,payload);
          RETURN NEW;
        END $$""")
        db.execute('CREATE TRIGGER jobs_event AFTER INSERT OR UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION capture_job_event()')
        db.execute('CREATE TRIGGER steps_event AFTER INSERT ON job_steps FOR EACH ROW EXECUTE FUNCTION capture_job_event()')
    else:
        db.execute("CREATE TRIGGER jobs_created_event AFTER INSERT ON jobs BEGIN INSERT INTO job_events(event,data_json) VALUES ('job.created',json_object('job_id',NEW.id,'status',NEW.status)); END")
        db.execute("CREATE TRIGGER jobs_status_event AFTER UPDATE OF status ON jobs WHEN OLD.status<>NEW.status BEGIN INSERT INTO job_events(event,data_json) VALUES (CASE WHEN NEW.status='running' THEN 'job.claimed' ELSE 'job.status_changed' END,json_object('job_id',NEW.id,'status',NEW.status)); END")
        db.execute("CREATE TRIGGER steps_event AFTER INSERT ON job_steps BEGIN INSERT INTO job_events(event,data_json) VALUES ('job.step',json_object('job_id',NEW.job_id,'step_idx',NEW.idx,'kind',NEW.kind)); END")
