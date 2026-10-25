"""Only this service can reach the public web; all reads use pinned addresses."""
import base64
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from orchestrator_core.tools.read.shared_client import _safe_request
from orchestrator_core.exceptions import SSRFViolationError

app = FastAPI()
logger = logging.getLogger("sandbox_egress")


class ReadRequest(BaseModel):
    url: str
    method: str = "GET"
    allowed_domains: list[str] = Field(default_factory=list)
    denied_domains: list[str] = Field(default_factory=list)
    timeout_s: float = Field(default=15, gt=0, le=30)
    max_bytes: int = Field(default=1048576, gt=0, le=1048576)


@app.post("/read")
def read(req: ReadRequest):
    try:
        response = _safe_request(req.method, req.url, allowed_domains=tuple(req.allowed_domains),
                                 denied_domains=tuple(req.denied_domains),
                                 timeout_s=req.timeout_s, max_bytes=req.max_bytes)
        return {"url": response.url, "status": response.status_code,
                "content_type": response.headers.get("Content-Type", "text/plain"),
                "body": base64.b64encode(response.content).decode("ascii")}
    except SSRFViolationError as exc:
        logger.warning("Read blocked: %s", exc)
        raise HTTPException(403, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Read failed: %s", type(exc).__name__)
        raise HTTPException(502, detail="Read gateway failed") from exc
