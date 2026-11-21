import asyncio
import logging
import os
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_REQUEST_TIMEOUT = float(os.environ["LLM_TIMEOUT"])
DEFAULT_TEMPERATURE = 0.4
DEFAULT_MAX_TOKENS = int(os.environ["LLM_MAX_TOKENS"])


def _require_env(name: str) -> str:
    value = os.environ[name].strip()
    if not value:
        raise ValueError(f"Variável de ambiente obrigatória vazia: {name}")
    return value


def _normalize_completions_url(raw_url: str) -> str:
    cleaned = raw_url.strip()
    if cleaned and not cleaned.rstrip("/").endswith("/chat/completions"):
        return cleaned.rstrip("/") + "/chat/completions"
    return cleaned


class BaseLLMAdapter(ABC):
    """Interface base (Adapter) para provedores de Chat Completions."""

    def __init__(self, api_key: str, url: str, model: str) -> None:
        self.api_key = api_key.strip()
        self.url = _normalize_completions_url(url)
        self.model = model.strip()
        if not self.api_key or not self.url or not self.model:
            raise ValueError(f"Configuração incompleta para {self.__class__.__name__}: api_key, url e model são obrigatórios.")

    @abstractmethod
    def build_payload(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Monta o payload específico aceito pelo provedor."""


class ICUnicampAdapter(BaseLLMAdapter):
    """Adapter para o servidor Ollama/OpenWebUI do IC-Unicamp (inclui options.num_predict)."""

    def __init__(
        self,
        api_key: str | None = None,
        url: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key if api_key is not None else _require_env("LLM_API_KEY_IC"),
            url=url if url is not None else _require_env("LLM_API_URL_IC"),
            model=model if model is not None else _require_env("LLM_MODEL_IC"),
        )

    def build_payload(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        model: str | None = None,
    ) -> dict[str, Any]:
        return {
            "model": (model or self.model).strip(),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "options": {"num_predict": max_tokens},
            "messages": messages,
        }


class NvidiaBuildAdapter(BaseLLMAdapter):
    """Adapter para a API do NVIDIA Build / NIM (OpenAI-compatible)."""

    def __init__(
        self,
        api_key: str | None = None,
        url: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key if api_key is not None else _require_env("LLM_API_KEY"),
            url=url if url is not None else _require_env("LLM_API_URL"),
            model=model if model is not None else _require_env("LLM_MODEL"),
        )

    def build_payload(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        model: str | None = None,
    ) -> dict[str, Any]:
        return {
            "model": (model or self.model).strip(),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
            "chat_template_kwargs": {"enable_thinking": False},
        }


def create_llm_adapter(
    provider: str | None = None,
    api_key: str | None = None,
    url: str | None = None,
    model: str | None = None,
) -> BaseLLMAdapter:
    """Seleciona o Adapter de acordo com o provider ou variável LLM_PROVIDER ('nvidia' ou 'ic')."""
    selected = (provider if provider is not None else _require_env("LLM_PROVIDER")).strip().lower()
    if selected == "ic":
        return ICUnicampAdapter(api_key=api_key, url=url, model=model)
    if selected == "nvidia":
        return NvidiaBuildAdapter(api_key=api_key, url=url, model=model)
    raise ValueError(f"LLM_PROVIDER inválido: '{selected}'. Valores suportados: 'nvidia' ou 'ic'.")


class LLMClient:
    """Cliente Python assíncrono para comunicação com a API do LLM."""

    def __init__(
        self,
        api_key: str | None = None,
        url: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> None:
        self.adapter = create_llm_adapter(
            provider=provider,
            api_key=api_key,
            url=url,
            model=model,
        )

    @property
    def api_key(self) -> str:
        return self.adapter.api_key

    @property
    def url(self) -> str:
        return self.adapter.url

    @property
    def model(self) -> str:
        return self.adapter.model

    async def generate_reply(
        self,
        message: str,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model: str | None = None,
    ) -> str:
        """Envia mensagem para o LLM e retorna o texto da resposta gerada."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        payload = self.adapter.build_payload(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )

        retry_delays = (1.0, 3.0)
        async with httpx.AsyncClient(timeout=DEFAULT_REQUEST_TIMEOUT) as client:
            for attempt in range(len(retry_delays) + 1):
                response = await client.post(self.url, headers=headers, json=payload)
                if response.status_code == 429 and attempt < len(retry_delays):
                    wait_sec = retry_delays[attempt]
                    retry_after = response.headers.get("retry-after")
                    if retry_after and retry_after.replace(".", "", 1).isdigit():
                        wait_sec = min(float(retry_after), 10.0)
                    else:
                        match = re.search(r"try again in (\d+(?:\.\d+)?)(ms|s)", response.text)
                        if match:
                            val, unit = float(match.group(1)), match.group(2)
                            wait_sec = min((val / 1000.0 if unit == "ms" else val) + 0.1, 10.0)
                    logger.warning(f"LLM retornou 429; aguardando {wait_sec:.1f}s (tentativa {attempt + 1}/{len(retry_delays)})...")
                    await asyncio.sleep(wait_sec)
                    continue
                break

            if response.status_code != 200:
                logger.error(
                    f"Erro na chamada do LLM ({response.status_code}): {response.text}"
                )
                raise RuntimeError(f"Erro ao comunicar com LLM: {response.status_code}")

            data: dict[str, Any] = response.json()
            choice_message = data["choices"][0]["message"]
            content = str(choice_message.get("content") or "").strip()
            if not content:
                raise RuntimeError("LLM retornou resposta vazia.")
            return content
