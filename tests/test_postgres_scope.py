import os
import pytest
from orchestrator_core.core.ownership import execution_owner
from orchestrator_core.storage.postgres import connect


@pytest.fixture
def connection():
    url = os.environ.get('PHASE2_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Disposable PostgreSQL database required')
    db = connect(url, pooled=True)
    try:
        yield db
    finally:
        db.close()


def current(db):
    return db.execute("SELECT current_setting('app.user_id',true)").fetchone()[0]


def test_owner_scope_does_not_leak_between_transactions(connection):
    marker = execution_owner.set('alice')
    try:
        assert current(connection) == 'alice'
        with connection:
            assert current(connection) == 'alice'
    finally:
        execution_owner.reset(marker)
    assert current(connection) == ''
    marker = execution_owner.set('bob')
    try:
        connection.execute('BEGIN IMMEDIATE')
        assert current(connection) == 'bob'
        connection.rollback()
    finally:
        execution_owner.reset(marker)
    assert current(connection) == ''


def test_mid_transaction_owner_switch_is_rejected(connection):
    marker = execution_owner.set('alice')
    try:
        connection.execute('BEGIN IMMEDIATE')
        other = execution_owner.set('bob')
        try:
            with pytest.raises(RuntimeError, match='Cannot change account'):
                current(connection)
        finally:
            execution_owner.reset(other)
        assert current(connection) == 'alice'
        connection.rollback()
    finally:
        execution_owner.reset(marker)


def test_pool_reuse_has_no_previous_account(connection):
    url = os.environ['PHASE2_TEST_DATABASE_URL']
    marker = execution_owner.set('alice')
    try:
        assert current(connection) == 'alice'
        connection.close()
    finally:
        execution_owner.reset(marker)
    other = connect(url)
    try:
        assert current(other) == ''
    finally:
        other.close()
