import json
import os
import statistics
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import llm
from .catalog import DATA_END, DATA_START, OPS, get_catalog
from .checks import review
from .filters import compile_where
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("COHORT_DB", str(ROOT / "data" / "patients.duckdb"))
LOG_PATH = os.environ.get("COHORT_LOG", str(ROOT / "data" / "events.jsonl"))
state = {}


@asynccontextmanager
async def lifespan(app):
    state["store"] = Store(DB_PATH)
    yield


app = FastAPI(title="ReadBack", lifespan=lifespan)


class DraftIn(BaseModel):
    request: str = Field(min_length=1, max_length=1000)


class ReviewIn(BaseModel):
    request: str = Field(default="", max_length=1000)
    filter: list = Field(default_factory=list)


class RunIn(ReviewIn):
    drafted: list | None = None
    draft_id: str | None = None


def _log(event: dict):
    event["ts"] = time.time()
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


@app.get("/api/meta")
def meta():
    cfg = llm.settings()
    try:
        model, reachable = llm.served_model(cfg), True
    except Exception:
        model, reachable = cfg["model"] or None, False
    store = state["store"]
    return {"model": model, "reachable": reachable, "hardware": cfg["hardware"],
            "patients": store.total, "data_start": DATA_START, "data_end": DATA_END,
            "synthetic": True}


@app.get("/api/catalog")
def catalog():
    cat = get_catalog()
    return {
        "attrs": [{"key": a.key, "kind": a.kind, "label": a.label, "lo": a.lo, "hi": a.hi,
                   "values": list(a.values), "unit": a.unit, "note": a.note,
                   "ops": list(OPS[a.kind])} for a in cat.attrs.values()],
        "conditions": [{"key": k, **{f: c[f] for f in ("name", "icd10", "chapter")}}
                       for k, c in cat.conditions.items()],
        "chapters": [{"key": k, "name": c["name"], "icd10": c["icd10"]}
                     for k, c in cat.chapters.items()],
        "regions": [{"key": k, "name": r["name"], "area": r["area"]}
                    for k, r in cat.regions.items()],
        "areas": [{"key": k, "name": a["name"], "members": a["members"]}
                  for k, a in cat.areas.items()],
    }


@app.post("/api/draft")
def draft(body: DraftIn):
    out = llm.draft(body.request)
    report = review(body.request, out["filter"])
    draft_id = f"{time.time_ns():x}"
    _log({"type": "draft", "id": draft_id, "request": body.request, "model": out["model"],
          "ms": out["ms"], "error": out["error"], "filter": report.filter,
          "checks": sorted({i.check for i in report.issues}),
          "levels": sorted({i.level for i in report.issues}), "runnable": report.runnable})
    return {"id": draft_id, "request": body.request, "note": out["note"],
            "llm": {k: out[k] for k in ("model", "ms", "tokens", "error")},
            **report.as_dict()}


@app.post("/api/review")
def review_filter(body: ReviewIn):
    return review(body.request, body.filter).as_dict()


@app.post("/api/run")
def run(body: RunIn):
    report = review(body.request, body.filter)
    if not report.runnable:
        raise HTTPException(422, detail={"message": "the filter has blocking issues",
                                         "issues": [i.as_dict() for i in report.issues]})
    result = state["store"].run(report.where, report.params)
    cat = get_catalog()
    result["steps"] = state["store"].funnel([compile_where([cl], cat)[1:]
                                             for cl in report.resolved])
    edited = body.drafted is not None and \
        review(body.request, body.drafted).filter != report.filter
    _log({"type": "run", "draft_id": body.draft_id, "request": body.request,
          "filter": report.filter, "edited": edited, "count": result["count"],
          "ms": result["ms"]})
    return {**report.as_dict(), "result": result, "edited": edited}


@app.get("/api/stats")
def stats():
    if not os.path.exists(LOG_PATH):
        return {"drafts": 0, "runs": 0}
    events = [json.loads(line) for line in open(LOG_PATH, encoding="utf-8") if line.strip()]
    drafts = [e for e in events if e["type"] == "draft" and not e.get("error")]
    runs = [e for e in events if e["type"] == "run"]
    flagged = [d for d in drafts if d["levels"]]
    by_check = {}
    for d in drafts:
        for c in d["checks"]:
            by_check[c] = by_check.get(c, 0) + 1
    latencies = [d["ms"] for d in drafts if d.get("ms")]
    return {
        "drafts": len(drafts), "runs": len(runs),
        "drafts_flagged": len(flagged),
        "runs_edited": sum(1 for r in runs if r.get("edited")),
        "by_check": by_check,
        "median_model_ms": statistics.median(latencies) if latencies else None,
    }


WEB = ROOT / "web"
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")
