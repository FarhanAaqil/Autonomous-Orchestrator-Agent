"""Export a deterministic OpenAPI contract without starting services or loading secrets."""
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
os.environ.update(AUTH_TOKEN="", ALLOW_INSECURE_LOCAL="true", ENVIRONMENT="development",
                  DATABASE_URL="", GROQ_API_KEY="", EXECUTOR_HMAC_SECRET="contract-only-not-a-production-secret")
from orchestrator_core.main import app
target = ROOT / "frontend" / "openapi.json"
content = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
if "--check" in sys.argv:
    if not target.exists() or target.read_text(encoding="utf-8") != content:
        raise SystemExit("API contract drift: regenerate frontend/openapi.json and client types")
else:
    target.write_text(content, encoding="utf-8")
