"""uv run uvicorn presend_check.server:app --reload

POST /check         {prospect, draft, fix?} -> CheckResult
POST /check/stream  same body -> NDJSON progress events, last one is {"type": "result"}
GET  /cases         the labelled demo cases
"""

import json
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import check
from .models import CheckResult, ProspectRecord

app = FastAPI(title="presend-fact-check")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"],
                   allow_headers=["*"])
CASES = Path(__file__).resolve().parent.parent / "cases"


class CheckRequest(BaseModel):
    prospect: ProspectRecord
    draft: str
    fix: bool = False
    fresh: bool = False


@app.post("/check")
def check_endpoint(req: CheckRequest) -> CheckResult:
    return check(req.prospect, req.draft, fix=req.fix, fresh=req.fresh)


@app.post("/check/stream")
def check_stream(req: CheckRequest) -> StreamingResponse:
    q: queue.Queue = queue.Queue()

    def work():
        try:
            check(req.prospect, req.draft, fix=req.fix, fresh=req.fresh, on_event=q.put)
        except Exception as e:  # surface to the UI instead of a hung stream
            q.put({"type": "error", "message": str(e)})
        q.put(None)

    threading.Thread(target=work, daemon=True).start()

    def events():
        while (e := q.get()) is not None:
            yield json.dumps(e, default=str) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.get("/cases")
def cases() -> list[dict]:
    return [{"id": p.stem, **json.loads(p.read_text())} for p in sorted(CASES.glob("*.json"))]


@app.get("/results")
def results() -> dict:
    p = CASES.parent / "results" / "latest.json"
    if not p.exists():
        raise HTTPException(404, "run `python cli.py --all` first")
    data = json.loads(p.read_text())
    return {"summary": data["summary"], "rows": [{k: v for k, v in r.items() if k != "result"}
                                                 for r in data["rows"]]}
