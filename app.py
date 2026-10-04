import os
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="JARVIS WebUI")
HERMES_URL = os.getenv("HERMES_URL", "http://hermes-agent:8642/v1").rstrip("/")
HERMES_API_KEY = os.getenv("HERMES_API_KEY", "")
TIMEOUT = int(os.getenv("HERMES_TIMEOUT", "120"))

def headers():
    return {"Authorization": f"Bearer {HERMES_API_KEY}", "Content-Type": "application/json"}

class Chat(BaseModel):
    message: str

@app.get("/")
def root():
    return FileResponse("/app/index.html")

@app.get("/api/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(HERMES_URL.replace("/v1", "") + "/health")
        return {"ok": r.is_success, "hermes": r.json() if r.is_success else None}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/models")
async def models():
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(HERMES_URL + "/models", headers=headers())
            r.raise_for_status()
            data = r.json().get("data", [])
        return {"models": [x.get("id") for x in data if x.get("id")]}
    except Exception:
        return {"models": ["hermes-agent"]}

@app.post("/api/chat")
async def chat(x: Chat):
    payload = {
        "model": "hermes-agent",
        "messages": [{"role": "user", "content": x.message}],
        "stream": False
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(HERMES_URL + "/chat/completions", headers=headers(), json=payload)
            if r.status_code >= 400:
                raise HTTPException(r.status_code, f"Hermes respondió HTTP {r.status_code}: {r.text[:500]}")
            j = r.json()
        answer = j["choices"][0]["message"]["content"]
        return {"answer": answer, "model": "hermes-agent", "provider": "Hermes Agent", "failed": []}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, f"No pude comunicarme con Hermes Agent: {e}")

@app.post("/api/providers")
async def providers():
    raise HTTPException(409, "Los proveedores ahora los administra Hermes Agent; el panel ya no salta Hermes.")

@app.post("/api/models/reorder")
async def reorder():
    return {"models": ["hermes-agent"]}

@app.post("/api/settings")
async def settings():
    return {"ok": True}
