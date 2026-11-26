import pytest
from fastapi import HTTPException
from orchestrator_core.core.admission import slot, _active


def test_busy_account_leaves_capacity_for_others():
    with slot('alice', 1):
        with pytest.raises(HTTPException) as error:
            with slot('alice', 1):
                pass
        assert error.value.status_code == 429
        with slot('bob', 1):
            assert _active == {'alice': 1, 'bob': 1}
    assert not _active


def test_failure_releases_capacity():
    with pytest.raises(RuntimeError):
        with slot('alice', 1):
            raise RuntimeError('fixture')
    with slot('alice', 1):
        assert _active['alice'] == 1
    assert not _active


def test_global_capacity_remains_bounded():
    from contextlib import ExitStack
    with ExitStack() as stack:
        for index in range(8):
            stack.enter_context(slot(str(index), 1))
        with pytest.raises(HTTPException) as error:
            with slot('ninth', 1):
                pass
        assert error.value.status_code == 503
    assert not _active
