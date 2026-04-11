.PHONY: up down migrate dev worker test

up:
	docker compose up -d
	@echo "Waiting for services..."
	@docker compose exec postgres sh -c 'until pg_isready -U adserver; do sleep 1; done'
	@echo "Postgres and Redis are ready."

down:
	docker compose down

migrate:
	.venv/bin/alembic upgrade head

dev:
	.venv/bin/uvicorn main:app --reload --port 8000

worker:
	.venv/bin/celery -A workers.celery_app worker --loglevel=info

test:
	.venv/bin/python test_pipeline.py
