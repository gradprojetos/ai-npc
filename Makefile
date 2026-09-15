.DEFAULT_GOAL := up
.PHONY: up down logs migration migrate rollback history

up:
	docker compose up -d

build:
	docker compose up --build -d

down:
	docker compose down -v

logs:
	docker compose logs -f

migration:
	docker compose run --rm api uv run alembic -c db/alembic.ini revision --autogenerate -m "$(name)"

migrate:
	docker compose run --rm api uv run alembic -c db/alembic.ini upgrade head

rollback:
	docker compose run --rm api uv run alembic -c db/alembic.ini downgrade -1

history:
	docker compose run --rm api uv run alembic -c db/alembic.ini history