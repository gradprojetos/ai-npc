FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN pip install --no-cache-dir uv \
    && uv sync --frozen

COPY . .

COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY api /app/api

CMD ["uv", "run", "python", "db_init/db_init.py"]