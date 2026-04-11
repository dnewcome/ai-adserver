import os
import sys

# Ensure project root is on the path regardless of how the worker is launched
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celery import Celery

from config import settings

celery_app = Celery(
    "adserver",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    result_expires=86400,          # keep results in Redis for 24 hours
    task_acks_late=True,           # only ack after task completes (safer on crash)
    worker_prefetch_multiplier=1,  # one task at a time per worker slot
)
