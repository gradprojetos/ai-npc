migration:
	docker compose run --rm db_init uv run alembic revision --autogenerate -m "$(name)"

migrate:
	docker compose run --rm db_init uv run alembic upgrade head