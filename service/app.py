"""FastAPI app for the live Design Council (phase 1: JSON input). See docs/LIVE_APP_BRIEF.md.

    .venv-service/bin/uvicorn service.app:create_app --factory --port 8000              # live (needs ANTHROPIC_API_KEY)
    LIVE_MOCK=1 .venv-service/bin/uvicorn service.app:create_app --factory --port 8000  # no network

Endpoints:
    POST /encodings/validate   raw encoding JSON  -> ValidationReport
    POST /runs                 RunRequest         -> JobCreated (202), or 409 with a CostEstimate
                                                     until confirm_cost is true, 429 at the daily cap
    GET  /runs/{job_id}/events server-sent events (resume with the Last-Event-ID header)
    GET  /runs/{job_id}        JobResult
    GET  /runs                 history (JobSummary list)

Access: if LIVE_PASSWORD is set, every request must send it in the X-Live-Password
header. The events endpoint also accepts ?password=, because browser EventSource cannot
set headers. The Anthropic key never leaves the server.
"""

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from design_council.run_logging import utc_now_iso

from service import runner
from service.config import ESTIMATE_USD, Settings, settings_from_env
from service.schemas import (
    ConditionResult,
    CostEstimate,
    JobCreated,
    JobResult,
    JobSummary,
    RunRequest,
    ValidationReport,
)
from service.store import Store
from service.validation import validate_encoding, validate_payload

TERMINAL = {"succeeded", "failed", "interrupted"}


def create_app(settings: Settings | None = None, client_factory=runner.make_client) -> FastAPI:
    settings = settings or settings_from_env()
    store = Store(settings.db_path, settings.jobs_root)
    pool = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="live-run")
    app = FastAPI(title="Design Council live service", version="0.1.0")
    app.state.settings, app.state.store, app.state.pool = settings, store, pool

    def check_password(x_live_password: str | None = Header(default=None),
                       password: str | None = Query(default=None)):
        if settings.password and settings.password not in (x_live_password, password):
            raise HTTPException(status_code=401, detail="password required")

    def summary(job: dict) -> JobSummary:
        return JobSummary(**{k: job[k] for k in JobSummary.model_fields})

    @app.post("/encodings/validate", response_model=ValidationReport, dependencies=[Depends(check_password)])
    def validate(payload: dict = Body(...)):
        _, report = validate_payload(payload)
        return report

    @app.post("/runs", status_code=202, response_model=JobCreated, dependencies=[Depends(check_password)])
    def start_run(req: RunRequest):
        report = validate_encoding(req.encoding)
        if not report.valid:
            raise HTTPException(status_code=422, detail=report.model_dump())
        conditions = list(dict.fromkeys(req.conditions))
        estimate = round(sum(ESTIMATE_USD[c] for c in conditions), 2)
        spent = store.spent_today(utc_now_iso()[:10])
        cost = CostEstimate(conditions=conditions, estimate_usd=estimate, spent_today_usd=round(spent, 2),
                            daily_cap_usd=settings.daily_cap_usd,
                            message=f"Estimated cost ${estimate:.2f}. Resend with confirm_cost=true to start.")
        if spent + estimate > settings.daily_cap_usd:
            cost.message = (f"Daily cap reached: ${spent:.2f} spent or committed today, cap "
                            f"${settings.daily_cap_usd:.2f}. No new runs until tomorrow (UTC).")
            return JSONResponse(status_code=429, content=cost.model_dump())
        if not req.confirm_cost:
            return JSONResponse(status_code=409, content=cost.model_dump())
        job_id = uuid.uuid4().hex[:12]
        store.create(job_id, req.encoding.workflow_id, req.encoding.name, conditions, req.profile,
                     req.encoding.model_dump_json(), estimate)
        store.emit(job_id, "job_queued", conditions=conditions, estimate_usd=estimate)
        pool.submit(runner.run_job, job_id, settings, store, client_factory)
        return JobCreated(job_id=job_id, status="queued", estimate_usd=estimate)

    @app.get("/runs/{job_id}/events", dependencies=[Depends(check_password)])
    def events(job_id: str, request: Request):
        if store.get(job_id) is None:
            raise HTTPException(status_code=404, detail="no such job")
        start = int(request.headers.get("last-event-id") or 0)

        def stream():
            sent, last_beat = start, time.monotonic()
            yield "retry: 3000\n\n"
            while True:
                for event_id, record in store.read_events(job_id, after=sent):
                    yield f"id: {event_id}\nevent: {record['event']}\ndata: {json.dumps(record)}\n\n"
                    sent = event_id
                job = store.get(job_id)
                if job["status"] in TERMINAL and not store.read_events(job_id, after=sent):
                    return
                if time.monotonic() - last_beat > 15:
                    yield ": keep-alive\n\n"
                    last_beat = time.monotonic()
                time.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/runs/{job_id}", response_model=JobResult, dependencies=[Depends(check_password)])
    def result(job_id: str):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="no such job")
        results = {}
        for condition in job["conditions"]:
            path = store.jobs_root / job_id / f"result_{condition}.json"
            if path.exists():
                results[condition] = ConditionResult.model_validate_json(path.read_text())
        return JobResult(job=summary(job), results=results)

    @app.get("/runs", response_model=list[JobSummary], dependencies=[Depends(check_password)])
    def history():
        return [summary(j) for j in store.list_jobs()]

    return app

