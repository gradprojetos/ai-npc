from fastapi import FastAPI, HTTPException
import httpx
import os
from dotenv import load_dotenv

# Carrega as chaves de API
load_dotenv()
api_key = os.getenv("LLM_API_KEY")
url = "https://llm.ic.unicamp.br/api/chat/completions"

app = FastAPI(title="LLM Gateway")

@app.post("/chat")
async def chat_with_llm(message: str):
    if not api_key:
        raise HTTPException(status_code=500, detail="Chave da API não configurada")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "gemma4:e4b",
        "temperature": 0.4,
        "max_tokens": 100,
        "messages": [
            {"role": "user", 
             "content": message
            }
        ]
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
            
        return response.json() # alterar se quiser recver só o texto da resposta, por exemplo: response.json().get("choices")[0].get("message").get("content")