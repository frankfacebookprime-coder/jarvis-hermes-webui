import json, os, time
from pathlib import Path
from typing import Optional
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app=FastAPI(title="JARVIS WebUI")
DATA=Path(os.getenv("DATA_DIR","/data")); DATA.mkdir(parents=True,exist_ok=True)
CFG=DATA/"config.json"
state={"providers":[],"models":[],"timeout":35}
if CFG.exists():
    try: state.update(json.loads(CFG.read_text()))
    except: pass
def save(): CFG.write_text(json.dumps(state,indent=2))
def clean_url(u): return u.rstrip("/")
def auth(k): return {"Authorization":f"Bearer {k}"} if k else {}

class Provider(BaseModel):
    name:str
    base_url:str
    api_key:str=""
class Chat(BaseModel): message:str
class Reorder(BaseModel): model:str; direction:int
class Settings(BaseModel): timeout:int=35

@app.get("/")
def root(): return FileResponse("/app/index.html")
@app.get("/api/health")
def health(): return {"ok":True}
@app.get("/api/models")
def models(): return {"models":state["models"]}

@app.post("/api/providers")
async def provider(p:Provider):
    url=clean_url(p.base_url)
    if not url: raise HTTPException(400,"Falta Base URL")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r=await c.get(url+"/models",headers=auth(p.api_key)); r.raise_for_status(); j=r.json()
        ms=[x.get("id") or x.get("name") for x in (j.get("data") or j.get("models") or []) if isinstance(x,dict)]
        ms=[x for x in ms if x]
    except Exception as e: raise HTTPException(400,f"No pude consultar /models: {e}")
    # One provider for now; easy and safe. Key stays server-side.
    state["providers"]=[{"name":p.name,"base_url":url,"api_key":p.api_key}]
    state["models"]=ms; save()
    return {"name":p.name,"models":ms}

@app.post("/api/models/reorder")
def reorder(x:Reorder):
    ms=state["models"]
    if x.model in ms:
        i=ms.index(x.model); n=max(0,min(len(ms)-1,i+x.direction))
        ms[i],ms[n]=ms[n],ms[i]; save()
    return {"models":ms}

@app.post("/api/settings")
def settings(s:Settings):
    state["timeout"]=max(5,min(120,s.timeout));save();return {"ok":True}

def extract(j):
    try: return j["choices"][0]["message"]["content"]
    except: return None

@app.post("/api/chat")
async def chat(x:Chat):
    if not state["providers"] or not state["models"]: raise HTTPException(400,"Configura primero un proveedor y detecta modelos.")
    p=state["providers"][0]; failed=[]
    # sequential failover avoids duplicate successful generations and is predictable
    async with httpx.AsyncClient(timeout=state["timeout"]) as c:
        for model in state["models"]:
            try:
                r=await c.post(p["base_url"]+"/chat/completions",headers={**auth(p["api_key"]),"Content-Type":"application/json"},
                    json={"model":model,"messages":[{"role":"user","content":x.message}],"stream":False})
                if r.status_code>=400:
                    failed.append(f"{model} (HTTP {r.status_code})"); continue
                ans=extract(r.json())
                if ans:
                    return {"answer":ans,"model":model,"provider":p["name"],"failed":failed}
                failed.append(f"{model} (respuesta inválida)")
            except Exception as e:
                failed.append(f"{model} ({type(e).__name__})")
    raise HTTPException(503,"Todos los modelos fallaron. "+" | ".join(failed))
