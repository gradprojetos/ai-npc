FROM python:3.11-slim
  
WORKDIR /app
COPY . /app

# Instalar apenas o uv
RUN pip install uv

# Usar o uv para instalar as dependências
RUN uv sync

# Rodar o servidor usando o ambiente virtual criado pelo uv
CMD ["uv", "run", "uvicorn", "llm_gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]