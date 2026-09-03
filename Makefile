migration:
	docker compose exec app alembic revision --autogenerate -m "$(name)"

migrate:
	docker compose exec app alembic upgrade head