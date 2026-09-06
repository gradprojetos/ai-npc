import logging
import os
from typing import Any
from dotenv import load_dotenv

import httpx

load_dotenv()
logger = logging.getLogger(__name__)

# valores padrao para comunicacao com o servico llm
DEFAULT_LLM_URL = "https://llm.ic.unicamp.br/api/chat/completions"
DEFAULT_LLM_MODEL = "gemma4:e4b"
DEFAULT_REQUEST_TIMEOUT = 60.0
DEFAULT_TEMPERATURE = 0.4
DEFAULT_MAX_TOKENS = 150


class LLMClient:
    """Cliente Python assíncrono para comunicação com a API do LLM."""

    def __init__(
        self,
        api_key: str | None = None,
        url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.url = url or os.getenv("LLM_API_URL", DEFAULT_LLM_URL)
        self.model = model or os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)

    async def generate_reply(
        self,
        message: str,
        system_prompt: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """Envia mensagem para o LLM e retorna o texto da resposta gerada."""
        if not self.api_key:
            raise ValueError("LLM_API_KEY não configurada nas variáveis de ambiente.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # monta a lista de mensagens no padrao chat completions
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        # envia a requisicao assincrona para o endpoint do gateway
        async with httpx.AsyncClient(timeout=DEFAULT_REQUEST_TIMEOUT) as client:
            response = await client.post(self.url, headers=headers, json=payload)

            if response.status_code != 200:
                logger.error(
                    f"Erro na chamada do LLM ({response.status_code}): {response.text}"
                )
                raise RuntimeError(f"Erro ao comunicar com LLM: {response.status_code}")

            data: dict[str, Any] = response.json()
            return str(data["choices"][0]["message"]["content"])
