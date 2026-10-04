import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="JARVIS WebUI")
DATA = Path("/data")
DATA.mkdir(parents=True, exist_ok=True)
CONFIG = DATA / "config.json"
TIMEOUT = int(os.getenv("HERMES_TIMEOUT", "120"))

def load_config():
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"providers": [], "models": []}

def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def auth_headers(key):
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

class Chat(BaseModel):
    message: str

class Provider(BaseModel):
    name: str
    base_url: str
    api_key: str

class Reorder(BaseModel):
    models: list[str]

@app.get("/")
def root():
    return FileResponse("/app/index.html")

@app.get("/api/health")
async def health():
    return {"ok": True}

@app.get("/api/models")
async def models():
    cfg = load_config()
    return {"models": cfg.get("models", [])}

@app.post("/api/providers")
async def providers(p: Provider):
    base = p.base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(base + "/models", headers=auth_headers(p.api_key))
            r.raise_for_status()
            data = r.json().get("data", [])
        ids = [m.get("id") for m in data if isinstance(m, dict) and m.get("id")]
        if not ids:
            raise HTTPException(400, "El proveedor respondió, pero no devolvió modelos.")
        cfg = load_config()
        cfg["providers"] = [{"name": p.name, "base_url": base, "api_key": p.api_key}]
        old = cfg.get("models", [])
        cfg["models"] = [m for m in old if m in ids] + [m for m in ids if m not in old]
        save_config(cfg)
        return {"ok": True, "models": cfg["models"], "count": len(cfg["models"])}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"No pude detectar modelos: {e}")

@app.post("/api/models/reorder")
async def reorder(x: Reorder):
    cfg = load_config()
    known = cfg.get("models", [])
    cfg["models"] = [m for m in x.models if m in known] + [m for m in known if m not in x.models]
    save_config(cfg)
    return {"models": cfg["models"]}

@app.post("/api/chat")
async def chat(x: Chat):
    cfg = load_config()
    providers = cfg.get("providers", [])
    models = cfg.get("models", [])
    if not providers or not models:
        raise HTTPException(400, "Configura un proveedor y pulsa Guardar y detectar.")
    failed = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        for provider in providers:
            url = provider["base_url"].rstrip("/") + "/chat/completions"
            for model in models:
                try:
                    payload = {"model": model, "messages": [{"role": "user", "content": x.message}], "stream": False}
                    r = await c.post(url, headers=auth_headers(provider["api_key"]), json=payload)
                    if r.status_code >= 400:
                        failed.append({"provider": provider["name"], "model": model, "error": f"HTTP {r.status_code}"})
                        continue
                    j = r.json()
                    answer = j["choices"][0]["message"]["content"]
                    return {"answer": answer, "model": model, "provider": provider["name"], "failed": failed}
                except Exception as e:
                    failed.append({"provider": provider["name"], "model": model, "error": str(e)[:160]})
    raise HTTPException(503, {"message": "No hubo ningún modelo disponible.", "failed": failed})

@app.post("/api/settings")
async def settings():
    return {"ok": True}
