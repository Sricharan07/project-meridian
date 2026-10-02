"""The local app: a JSON API over the knowledge base and the chat, plus the static UI.

No logic lives here. Every endpoint is one call into KnowledgeBase or Chat, so
what the UI shows is exactly what the tests and the chat model see.
"""

from dataclasses import asdict
from functools import cache

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from meridian import config, corrections, graph, ingest, learning
from meridian.chat.agent import Chat
from meridian.knowledge import KnowledgeBase

app = FastAPI(title="Meridian", docs_url="/api/docs", redoc_url=None)
WEB = config.ROOT / "web"


@app.middleware("http")
async def revalidate(request, call_next):
    # The UI and kb/ change when either is edited or rebuilt; without this a browser keeps an old
    # module next to a new one. Revalidating costs a 304.
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-cache")
    return response


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
         "sheets": info["sheets"], "model_3d": k.model_3d(d) is not None,
         "added": info["upstream_path"].startswith("uploaded/")}
        for d, info in k.sheets.items()
    ]


@app.get("/api/bom")
def bom_rows() -> list[dict]:
    k = kb()
    return [{"row": r, "name": k.cell(r, "name").value, "family": k.cell(r, "family").value if k.cell(r, "family") else "",
             "drawings": k.drawings_of_row.get(r, [])} for r in k.bom_rows]


@app.get("/api/graph")
def knowledge_graph() -> dict:
    return kb().graph.to_dict()


@app.get("/api/graph/path")
def graph_path(a: str, b: str) -> dict:
    return graph.path(kb().graph, a, b)


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
    turn = chat().ask(question, q.history[-8:])
    if any(step["tool"] == "propose_correction" for step in turn.steps):
        _reload()  # the new proposal now shows on the part and in review
    return turn.to_dict()


class Decision(BaseModel):
    accept: bool
    by: str
    note: str = ""
    link: dict | None = None   # an added drawing: {"rows": [51], "status": "linked"}


@app.get("/api/corrections")
def list_corrections() -> list[dict]:
    k = kb()
    order = {"pending": 0, "accepted": 1, "rejected": 2}
    proposals = sorted(corrections.load(), key=lambda c: (order[c.status], c.id), reverse=False)
    known = lambda ref: ref in k.sheets or ref.startswith("BOM.")
    # A drawing added in the app is not in the knowledge base until it is accepted; it goes by the title read off it.
    return [asdict(c) | {"target_evidence": k.evidence(c.target),
                         "part": k.name(c.subject) if known(c.subject) else c.payload.get("title") or c.subject}
            for c in proposals]


@app.get("/api/learning")
def learning_timeline() -> dict:
    """What accepted corrections have changed, measured after each one in the order they were decided."""
    return learning.timeline(kb().corrections_log)


class Proposal(BaseModel):
    kind: str = "value"            # value | dispute | link | relation
    reason: str
    target: str = ""               # value, dispute: the observation
    value: str = ""
    drawing: str = ""              # link
    rows: list[int] = []
    status: str = ""
    a: str = ""                    # relation
    b: str = ""
    relation: str = ""
    remove: bool = False


@app.post("/api/corrections")
def file_correction(p: Proposal) -> dict:
    """A correction filed from the interface rather than the chat; it waits for review like any other."""
    k = kb()
    if not p.reason.strip():
        raise HTTPException(400, "Say why: a correction needs a reason.")
    try:
        if p.kind in ("value", "dispute"):
            c = corrections.propose(k, p.target, p.value, p.reason, "", k.corrections_log, kind=p.kind)
        elif p.kind == "link":
            c = corrections.propose_link(k, p.drawing, p.rows, p.status, p.reason, "", k.corrections_log)
        elif p.kind == "relation":
            c = corrections.propose_relation(k, p.a, p.b, p.relation, p.reason, "", remove=p.remove, log=k.corrections_log)
        else:
            raise ValueError(f'No kind of correction called "{p.kind}".')
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    _reload()
    return asdict(c)


@app.post("/api/ingest")
async def add_drawing(request: Request, subsystem: str, filename: str, reason: str) -> dict:
    """Upload a PDF as the request body. It is read now and waits for review before it joins the knowledge base."""
    body = await request.body()
    if len(body) > 40 * 1024 * 1024:
        raise HTTPException(413, "That file is larger than 40 MB.")
    if not reason.strip():
        raise HTTPException(400, "Say where the drawing comes from: an upload needs a reason.")
    k = kb()
    try:
        c = ingest.add(k, body, filename, subsystem, reason, log=k.corrections_log)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    _reload()
    return asdict(c)


@app.post("/api/corrections/{correction_id}/decision")
def decide(correction_id: str, d: Decision) -> dict:
    try:
        decided = corrections.decide(correction_id, d.accept, d.by, d.note, kb().corrections_log, link=d.link)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    _reload()
    return asdict(decided)


def _reload() -> None:
    kb.cache_clear()
    chat.cache_clear()


app.mount("/ingest", StaticFiles(directory=ingest.DIR, check_dir=False), name="ingest")
app.mount("/kb", StaticFiles(directory=config.KB), name="kb")
app.mount("/diagrams", StaticFiles(directory=config.DIAGRAMS), name="diagrams")
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/{path:path}", include_in_schema=False)
def page(path: str) -> FileResponse:
    """Every non-API path serves the app, so /part/D-026 and /review are shareable links."""
    return FileResponse(WEB / "index.html")
