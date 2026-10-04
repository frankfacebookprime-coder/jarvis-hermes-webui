import json, os
from pathlib import Path
from datetime import datetime, timezone
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="JARVIS WebUI")
DATA = Path("/data"); DATA.mkdir(parents=True, exist_ok=True)
CONFIG = DATA/"config.json"; MEMORY = DATA/"memory.json"; LOGS = DATA/"events.json"

def read(path, default):
    try: return json.loads(path.read_text("utf-8")) if path.exists() else default
    except Exception: return default

def write(path, obj): path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), "utf-8")

def cfg():
    x=read(CONFIG,{})
    return {"providers":x.get("providers",[]),"models":x.get("models",[]),"timeout":x.get("timeout",35),"system_prompt":x.get("system_prompt","Eres JARVIS, un asistente útil, directo y preciso.")}

def headers(key): return {"Authorization":f"Bearer {key}","Content-Type":"application/json"}

def event(kind,msg,**extra):
    x=read(LOGS,[]); x.append({"time":datetime.now(timezone.utc).isoformat(),"kind":kind,"message":msg,**extra}); write(LOGS,x[-300:])

class Chat(BaseModel):
    message: str
    model: str | None = None
    mode: str = "direct"

class Provider(BaseModel):
    name: str
    base_url: str
    api_key: str

class Reorder(BaseModel):
    models: list[str]

class Settings(BaseModel):
    timeout: int = 35
    system_prompt: str = "Eres JARVIS, un asistente útil, directo y preciso."

class MemoryItem(BaseModel):
    text: str

@app.get("/")
def root(): return FileResponse("/app/index.html")

@app.get("/api/health")
def health(): return {"ok":True,"version":"2.1"}

@app.get("/api/state")
def state():
    c=cfg()
    return {"models":c["models"],"providers":[{"name":p["name"],"base_url":p["base_url"]} for p in c["providers"]],"timeout":c["timeout"],"system_prompt":c["system_prompt"],"memory_count":len(read(MEMORY,[]))}

@app.get("/api/models")
def models(): return {"models":cfg()["models"]}

@app.get("/api/logs")
def logs(): return {"logs":read(LOGS,[])[-100:]}

@app.get("/api/memory")
def memory(): return {"items":read(MEMORY,[])}

@app.post("/api/memory")
def add_memory(x:MemoryItem):
    items=read(MEMORY,[])
    item={"id":datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f"),"text":x.text.strip()}
    if item["text"]: items.append(item); write(MEMORY,items)
    return {"items":items}

@app.delete("/api/memory/{mid}")
def del_memory(mid:str):
    items=[x for x in read(MEMORY,[]) if x.get("id")!=mid]; write(MEMORY,items); return {"items":items}

@app.post("/api/providers")
async def providers(p:Provider):
    base=p.base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r=await client.get(base+"/models",headers=headers(p.api_key)); r.raise_for_status()
        ids=[m.get("id") for m in r.json().get("data",[]) if isinstance(m,dict) and m.get("id")]
        if not ids: raise HTTPException(400,"El proveedor respondió, pero no devolvió modelos.")
        c=cfg(); c["providers"]=[{"name":p.name,"base_url":base,"api_key":p.api_key}]
        old=c["models"]; c["models"]=[m for m in old if m in ids]+[m for m in ids if m not in old]
        write(CONFIG,c); event("provider","Modelos detectados",provider=p.name,count=len(ids))
        return {"ok":True,"name":p.name,"models":c["models"],"count":len(ids)}
    except HTTPException: raise
    except Exception as e: raise HTTPException(502,f"No pude detectar modelos: {e}")

@app.post("/api/models/reorder")
def reorder(x:Reorder):
    c=cfg(); known=c["models"]
    c["models"]=[m for m in x.models if m in known]+[m for m in known if m not in x.models]
    write(CONFIG,c); return {"models":c["models"]}

@app.post("/api/settings")
def settings(x:Settings):
    c=cfg(); c["timeout"]=max(5,min(120,x.timeout)); c["system_prompt"]=x.system_prompt.strip() or c["system_prompt"]; write(CONFIG,c); return {"ok":True}

@app.post("/api/chat")
async def chat(x:Chat):
    c=cfg()
    if x.mode=="hermes":
        hurl=os.getenv("HERMES_URL","http://hermes-agent:8642/v1").rstrip("/")
        hkey=os.getenv("HERMES_API_KEY","")
        try:
            async with httpx.AsyncClient(timeout=c["timeout"]) as client:
                r=await client.post(hurl+"/chat/completions",headers=headers(hkey),json={"model":"hermes-agent","messages":[{"role":"user","content":x.message}],"stream":False})
            if r.status_code>=400: raise HTTPException(r.status_code,f"Hermes respondió HTTP {r.status_code}: {r.text[:300]}")
            ans=r.json()["choices"][0]["message"]["content"]
            event("hermes","Respuesta correcta",model="Hermes Agent")
            return {"answer":ans,"model":"Hermes Agent","provider":"Hermes","failed":[]}
        except HTTPException: raise
        except Exception as e:
            event("hermes_error","Hermes no disponible",error=str(e)[:160])
            raise HTTPException(503,f"Hermes no está disponible: {e}")

    if not c["providers"] or not c["models"]: raise HTTPException(400,"Configura un proveedor y detecta modelos.")
    mem=read(MEMORY,[])
    memtxt="\n".join("- "+m["text"] for m in mem[-20:])
    system=c["system_prompt"]+(("\n\nMemoria persistente:\n"+memtxt) if memtxt else "")
    ordered=list(c["models"])
    if x.model and x.model in ordered: ordered=[x.model]+[m for m in ordered if m!=x.model]
    failed=[]
    async with httpx.AsyncClient(timeout=c["timeout"]) as client:
        for p in c["providers"]:
            for model in ordered:
                try:
                    payload={"model":model,"messages":[{"role":"system","content":system},{"role":"user","content":x.message}],"stream":False}
                    r=await client.post(p["base_url"].rstrip("/")+"/chat/completions",headers=headers(p["api_key"]),json=payload)
                    if r.status_code>=400:
                        failed.append({"model":model,"error":f"HTTP {r.status_code}"}); event("failover","Modelo falló",model=model,error=f"HTTP {r.status_code}"); continue
                    ans=r.json()["choices"][0]["message"]["content"]
                    event("chat","Respuesta correcta",provider=p["name"],model=model,failed=len(failed))
                    return {"answer":ans,"model":model,"provider":p["name"],"failed":failed}
                except Exception as e:
                    failed.append({"model":model,"error":str(e)[:120]}); event("failover","Modelo falló",model=model,error=str(e)[:120])
    raise HTTPException(503,{"message":"No hubo ningún modelo disponible.","failed":failed})
