from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from workers.celery_app import celery_app

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Celery task states → our API states
_STATE_MAP = {
    "PENDING":  "queued",
    "STARTED":  "processing",
    "RETRY":    "processing",
    "SUCCESS":  "done",
    "FAILURE":  "failed",
    "REVOKED":  "cancelled",
}


class JobResponse(BaseModel):
    job_id: str
    status: str          # queued | processing | done | failed | cancelled
    result: dict | None = None
    error: str | None = None


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    """
    Poll a background task by job_id (Celery task ID).
    Returns status and, when done, the task result payload.
    """
    task: AsyncResult = celery_app.AsyncResult(job_id)

    state = _STATE_MAP.get(task.state, "unknown")
    result = None
    error = None

    if task.state == "SUCCESS":
        result = task.result if isinstance(task.result, dict) else {"value": task.result}
    elif task.state == "FAILURE":
        error = str(task.result)

    return JobResponse(job_id=job_id, status=state, result=result, error=error)
