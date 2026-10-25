"""Run repository tests with disposable state, no dotenv and no external sockets."""
import ipaddress
import os
from pathlib import Path
import socket
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
os.environ.update(GROQ_API_KEY="", AUTH_TOKEN="", API_BEARER_TOKEN="", ENABLE_REAL_EMAIL="false",
                  EXECUTOR_HMAC_SECRET="isolated-tests-only-secret-32-characters", ENVIRONMENT="development",
                  ACTION_EXECUTION_MODE="simulation", ALLOW_INSECURE_LOCAL="true")
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex


def guard(original):
    def connect(sock, address):
        try:
            allowed = ipaddress.ip_address(address[0]).is_loopback
        except (ValueError, TypeError):
            allowed = False
        if not allowed:
            raise RuntimeError("External connections are disabled in local tests")
        return original(sock, address)
    return connect


socket.socket.connect = guard(original_connect)
socket.socket.connect_ex = guard(original_connect_ex)
with tempfile.TemporaryDirectory(prefix="orchestrator-tests-", ignore_cleanup_errors=True) as temp:
    os.environ["DATABASE_PATH"] = str(Path(temp) / "test.db")
    os.environ["CHROMA_DB_DIR"] = str(Path(temp) / "chroma")
    os.chdir(temp)
    import pytest
    args = [str(ROOT / arg) if (ROOT / arg).exists() else arg for arg in sys.argv[1:]]
    code = pytest.main(["-q", "-p", "no:cacheprovider", "--tb=short", *args])
    from orchestrator_core.storage.db import _connection_pool
    _connection_pool.close_all()
    os.chdir(ROOT)
raise SystemExit(code)
