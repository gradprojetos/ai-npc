import os
import logging
import httpx

logger = logging.getLogger(__name__)

class LLMClient:
    """Cliente Python assíncrono para comunicação com a API do LLM."""
    
    def __init__(self, api_key: str | None = None, url: str | None = None):
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.url = url or os.getenv("LLM_API_URL", "https://llm.ic.unicamp.br/api/chat/completions")
        self.model = os.getenv("LLM_MODEL", "gemma4:e4b")

    async def generate_reply(
        self, 
        message: str, 
        system_prompt: str | None = None, 
        temperature: float = 0.4, 
        max_tokens: int = 150
    ) -> str:
        if not self.api_key:
            raise ValueError("LLM_API_KEY não configurada nas variáveis de ambiente.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(self.url, headers=headers, json=payload)
            
            if response.status_code != 200:
                logger.error(f"Erro na chamada do LLM ({response.status_code}): {response.text}")
                raise RuntimeError(f"Erro ao comunicar com LLM: {response.status_code}")

            data = response.json()
            return data["choices"][0]["message"]["content"]
