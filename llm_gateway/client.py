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

DEFAULT_REQUEST_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "12.0"))
DEFAULT_TEMPERATURE = 0.4
DEFAULT_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "90"))

_REASONING_MODEL_KEYWORDS = ("gpt-oss", "qwen", "deepseek", "r1", "qwq")


def _clean_env(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _normalize_completions_url(raw_url: str) -> str:
    cleaned = raw_url.strip()
    if cleaned and not cleaned.rstrip("/").endswith("/chat/completions"):
        return cleaned.rstrip("/") + "/chat/completions"
    return cleaned


class BaseLLMAdapter(ABC):
    """Interface base (Adapter) para provedores de Chat Completions."""

    def __init__(self, api_key: str | None, url: str, model: str) -> None:
        self.api_key = _clean_env(api_key)
        self.url = _normalize_completions_url(url)
        self.model = model.strip()

    @abstractmethod
    def build_payload(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Monta o payload específico aceito pelo provedor."""


class GroqAdapter(BaseLLMAdapter):
    """Adapter para a API da Groq (OpenAI-compatible estrito, com suporte a modelos de raciocínio)."""

    def __init__(
        self,
        api_key: str | None = None,
        url: str | None = None,
        model: str | None = None,
    ) -> None:
        resolved_key = (
            _clean_env(api_key)
            or _clean_env(os.getenv("LLM_API_KEY_GROQ"))
            or _clean_env(os.getenv("LLM_API_KEY"))
        )
        resolved_url = (
            _clean_env(url)
            or _clean_env(os.getenv("LLM_API_URL_GROQ"))
            or _clean_env(os.getenv("LLM_API_URL"))
            or ""
        )
        resolved_model = (
            _clean_env(model)
            or _clean_env(os.getenv("LLM_MODEL_GROQ"))
            or _clean_env(os.getenv("LLM_MODEL"))
            or ""
        )
        super().__init__(api_key=resolved_key, url=resolved_url, model=resolved_model)

    def build_payload(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        model: str | None = None,
    ) -> dict[str, Any]:
        target_model = (model or self.model).strip()
        is_reasoning = any(k in target_model.lower() for k in _REASONING_MODEL_KEYWORDS)
        effective_max_tokens = max_tokens + 250 if is_reasoning else max_tokens

        payload: dict[str, Any] = {
            "model": target_model,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
            "messages": messages,
        }
        if is_reasoning:
            payload["reasoning_effort"] = "low"
            payload["include_reasoning"] = False
        return payload


class OpenRouterAdapter(BaseLLMAdapter):
    """Adapter para OpenRouter (desativa reasoning tokens para preservar limite de saída)."""

    def __init__(
        self,
        api_key: str | None = None,
        url: str | None = None,
        model: str | None = None,
    ) -> None:
        resolved_key = (
            _clean_env(api_key)
            or _clean_env(os.getenv("LLM_API_KEY_OPENROUTER"))
            or _clean_env(os.getenv("LLM_API_KEY"))
        )
        resolved_url = (
            _clean_env(url)
            or _clean_env(os.getenv("LLM_API_URL_OPENROUTER"))
            or _clean_env(os.getenv("LLM_API_URL"))
            or ""
        )
        resolved_model = (
            _clean_env(model)
            or _clean_env(os.getenv("LLM_MODEL_OPENROUTER"))
            or _clean_env(os.getenv("LLM_MODEL"))
            or ""
        )
        super().__init__(api_key=resolved_key, url=resolved_url, model=resolved_model)

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
            "reasoning": {"effort": "none"},
            "messages": messages,
        }


class ICUnicampAdapter(BaseLLMAdapter):
    """Adapter para o servidor Ollama/OpenWebUI do IC-Unicamp (inclui options.num_predict)."""

    def __init__(
        self,
        api_key: str | None = None,
        url: str | None = None,
        model: str | None = None,
    ) -> None:
        resolved_key = _clean_env(api_key) or _clean_env(os.getenv("LLM_API_KEY_IC")) or _clean_env(os.getenv("LLM_API_KEY"))
        resolved_url = _clean_env(url) or _clean_env(os.getenv("LLM_API_URL_IC")) or _clean_env(os.getenv("LLM_API_URL")) or ""
        resolved_model = (
            _clean_env(model)
            or _clean_env(os.getenv("LLM_MODEL_IC"))
            or _clean_env(os.getenv("LLM_MODEL"))
            or ""
        )
        super().__init__(api_key=resolved_key, url=resolved_url, model=resolved_model)

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
        resolved_key = (
            _clean_env(api_key)
            or _clean_env(os.getenv("LLM_API_KEY_NVIDIA"))
            or _clean_env(os.getenv("LLM_API_KEY"))
        )
        resolved_url = (
            _clean_env(url)
            or _clean_env(os.getenv("LLM_API_URL_NVIDIA"))
            or _clean_env(os.getenv("LLM_API_URL"))
            or ""
        )
        resolved_model = (
            _clean_env(model)
            or _clean_env(os.getenv("LLM_MODEL_NVIDIA"))
            or _clean_env(os.getenv("LLM_MODEL"))
            or ""
        )
        super().__init__(api_key=resolved_key, url=resolved_url, model=resolved_model)

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
    """Seleciona o Adapter de acordo com o provider ou variável LLM_PROVIDER (default: 'groq')."""
    selected = (provider or os.getenv("LLM_PROVIDER") or "groq").strip().lower()
    if url:
        if "openrouter.ai" in url:
            return OpenRouterAdapter(api_key=api_key, url=url, model=model)
        if "unicamp.br" in url:
            return ICUnicampAdapter(api_key=api_key, url=url, model=model)
        if "groq.com" in url:
            return GroqAdapter(api_key=api_key, url=url, model=model)
        if "nvidia.com" in url:
            return NvidiaBuildAdapter(api_key=api_key, url=url, model=model)

    if selected in {"nvidia", "nvdia", "nvidia_build", "nim"}:
        return NvidiaBuildAdapter(api_key=api_key, url=url, model=model)
    if selected == "openrouter":
        return OpenRouterAdapter(api_key=api_key, url=url, model=model)
    if selected in {"ic", "unicamp", "ollama"}:
        return ICUnicampAdapter(api_key=api_key, url=url, model=model)
    return GroqAdapter(api_key=api_key, url=url, model=model)


class LLMClient:
    """Cliente Python assíncrono para comunicação com a API do LLM (default: GroqAdapter)."""

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
    def api_key(self) -> str | None:
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
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model: str | None = None,
    ) -> str:
        """Envia mensagem para o LLM e retorna o texto da resposta gerada."""
        if not self.api_key:
            raise ValueError("Chave de API do LLM (ex: LLM_API_KEY_GROQ) não configurada nas variáveis de ambiente.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        payload = self.adapter.build_payload(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )

        async with httpx.AsyncClient(timeout=DEFAULT_REQUEST_TIMEOUT) as client:
            for attempt in range(2):
                response = await client.post(self.url, headers=headers, json=payload)
                if response.status_code == 429 and attempt == 0:
                    wait_sec = 1.0
                    match = re.search(r"try again in (\d+(?:\.\d+)?)(ms|s)", response.text)
                    if match:
                        val, unit = float(match.group(1)), match.group(2)
                        wait_sec = (val / 1000.0 if unit == "ms" else val) + 0.1
                    if wait_sec <= 1.5:
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
