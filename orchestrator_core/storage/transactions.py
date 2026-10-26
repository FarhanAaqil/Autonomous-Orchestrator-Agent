"""Nested transactions that never commit the caller's unit of work."""
from contextlib import contextmanager
import uuid


@contextmanager
def transaction(db):
    nested = db.in_transaction
    savepoint = 'sp_' + uuid.uuid4().hex
    db.execute('SAVEPOINT '+savepoint if nested else 'BEGIN IMMEDIATE')
    try:
        yield db
        if nested:
            db.execute('RELEASE SAVEPOINT '+savepoint)
        else:
            db.commit()
    except BaseException:
        if nested:
            db.execute('ROLLBACK TO SAVEPOINT '+savepoint)
            db.execute('RELEASE SAVEPOINT '+savepoint)
        else:
            db.rollback()
        raise
