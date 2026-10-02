"""The local app: a JSON API over the knowledge base and the chat, plus the static UI.

No logic lives here. Every endpoint is one call into KnowledgeBase or Chat, so
what the UI shows is exactly what the tests and the chat model see.
"""

from functools import cache

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from meridian import config
from meridian.chat.agent import Chat
from meridian.knowledge import KnowledgeBase

app = FastAPI(title="Meridian", docs_url="/api/docs", redoc_url=None)
WEB = config.ROOT / "web"


@cache
def kb() -> KnowledgeBase:
    return KnowledgeBase.load()


@cache
def chat() -> Chat:
    return Chat(kb())


class Question(BaseModel):
    question: str
    history: list[dict] = []


@app.get("/api/status")
def status() -> dict:
    k = kb()
    return {
        "model": config.MODEL if config.OPENAI_API_KEY else None,
        "observations": len(k.obs),
        "drawings": len(k.sheets),
        "bom_rows": len(k.bom_rows),
        "relations": len(k.relations),
        "snapshot": {"revision": config.SOURCE_REVISION, "retrieved": config.SNAPSHOT_RETRIEVED},
    }


@app.get("/api/drawings")
def drawings() -> list[dict]:
    k = kb()
    return [
        {"ref": d, "name": k.drawing_name(d), "subsystem": info["subsystem"], "scan": info["degraded"],
         "bom_rows": k.links[d].parsed["rows"], "link_status": k.links[d].parsed["status"],
         "sheets": info["sheets"], "model_3d": k.model_3d(d) is not None}
        for d, info in k.sheets.items()
    ]


@app.get("/api/parts/{ref}")
def part(ref: str) -> dict:
    k = kb()
    if ref in k.sheets or (ref.startswith("BOM.") and ref[4:].isdigit() and int(ref[4:]) in k.bom_rows):
        return k.part(ref)
    raise HTTPException(404, f"No part {ref}")


@app.get("/api/evidence/{observation_id:path}")
def evidence(observation_id: str) -> dict:
    found = kb().evidence(observation_id)
    if found is None:
        raise HTTPException(404, f"No observation {observation_id}")
    return found


@app.post("/api/chat")
def ask(q: Question) -> dict:
    question = q.question.strip()
    if not question:
        raise HTTPException(400, "Empty question")
    return chat().ask(question, q.history[-8:]).to_dict()


app.mount("/kb", StaticFiles(directory=config.KB), name="kb")
app.mount("/diagrams", StaticFiles(directory=config.DIAGRAMS), name="diagrams")
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/{path:path}", include_in_schema=False)
def page(path: str) -> FileResponse:
    """Every non-API path serves the app, so /part/D-026 and /review are shareable links."""
    return FileResponse(WEB / "index.html")
