import pytest

from orchestrator_core.core import identity
from orchestrator_core.reset_password import reset_password


def test_recovery_replaces_password_and_revokes_sessions(db):
    identity.create_user(db, 'admin', 'old-fixture-password', 'administrator')
    token = identity.login(db, 'admin', 'old-fixture-password', 'test')
    reset_password(db, ' ADMIN ', 'new-fixture-password')
    assert identity.principal(db, token) is None
    assert identity.login(db, 'admin', 'old-fixture-password', 'test') is None
    assert identity.login(db, 'admin', 'new-fixture-password', 'test')


def test_short_password_leaves_account_unchanged(db):
    identity.create_user(db, 'admin', 'old-fixture-password', 'administrator')
    with pytest.raises(ValueError):
        reset_password(db, 'admin', 'short')
    assert identity.login(db, 'admin', 'old-fixture-password', 'test')
