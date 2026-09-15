FROM python:3.11-slim

WORKDIR /app

# Instala o uv
RUN pip install --no-cache-dir uv

# Copia os arquivos de dependências primeiro para aproveitar o cache do Docker
COPY pyproject.toml uv.lock ./

# Instala as dependências no venv
RUN uv sync --frozen --no-install-project

# Copia os arquivos da aplicação (o .dockerignore vai ignorar o .venv local)
COPY . /app

# Instala o projeto atual
RUN uv sync --frozen

# Garante que os binários do venv do container fiquem no PATH
ENV PATH="/app/.venv/bin:$PATH"

# Inicia o uvicorn lendo a variável de ambiente $API_PORT
CMD uv run uvicorn api.main:app --host 0.0.0.0 --port ${API_PORT:-8000} --reload
