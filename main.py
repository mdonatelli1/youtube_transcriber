"""
main.py — Backend FastAPI.
Lancement : uvicorn main:app --reload
"""

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database as db
import worker
from exporter import export_json, export_srt, export_txt

# ── Init ──────────────────────────────────────────────────────────────────────
db.init_db()
app = FastAPI(title="YouTube Transcriber")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Queue asyncio partagée avec le worker
_update_queue: asyncio.Queue = asyncio.Queue()
worker.set_update_queue(_update_queue)

# WebSocket clients connectés
_ws_clients: list[WebSocket] = []


# ── WebSocket — diffuse les mises à jour en temps réel ───────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    try:
        while True:
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        _ws_clients.remove(ws)


async def _broadcast_loop():
    """Tâche de fond : vide la queue et envoie à tous les clients WS."""
    while True:
        try:
            msg = _update_queue.get_nowait()
            dead = []
            for ws in _ws_clients:
                try:
                    await ws.send_text(json.dumps(msg))
                except Exception:
                    dead.append(ws)
            for ws in dead:
                _ws_clients.remove(ws)
        except asyncio.QueueEmpty:
            pass
        await asyncio.sleep(0.05)


@app.on_event("startup")
async def startup():
    asyncio.create_task(_broadcast_loop())


# ── Routes HTML ───────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    return Path("static/index.html").read_text(encoding="utf-8")


# ── API — File d'attente ──────────────────────────────────────────────────────
class EnqueueRequest(BaseModel):
    url: str
    model: str = "small"
    language: str = "auto"


@app.post("/api/enqueue")
async def enqueue(req: EnqueueRequest):
    lang = None if req.language == "auto" else req.language
    job = worker.Job(
        job_id=str(uuid.uuid4())[:8],
        url=req.url,
        model=req.model,
        language=lang,
    )
    worker.enqueue(job)
    return {"job_id": job.job_id}


@app.get("/api/jobs")
async def get_jobs():
    return worker.get_all_jobs()


# ── API — Chaîne ──────────────────────────────────────────────────────────────
class ChannelRequest(BaseModel):
    url: str


@app.post("/api/channel/videos")
async def channel_videos(req: ChannelRequest):
    try:
        videos = worker.fetch_channel_videos(req.url)
        return {"videos": videos}
    except Exception as e:
        return {"error": str(e)}


class BatchRequest(BaseModel):
    video_ids: list[str]  # liste d'IDs YouTube
    model: str = "small"
    language: str = "auto"


@app.post("/api/channel/enqueue-batch")
async def enqueue_batch(req: BatchRequest):
    lang = None if req.language == "auto" else req.language
    job_ids = []
    for vid_id in req.video_ids:
        url = f"https://www.youtube.com/watch?v={vid_id}"
        job = worker.Job(
            job_id=str(uuid.uuid4())[:8],
            url=url,
            model=req.model,
            language=lang,
        )
        worker.enqueue(job)
        job_ids.append(job.job_id)
    return {"job_ids": job_ids}


# ── API — Historique ──────────────────────────────────────────────────────────
@app.get("/api/history")
async def history():
    return db.get_history()


@app.get("/api/transcript/{tid}")
async def get_transcript(tid: int):
    t = db.get_transcript(tid)
    if not t:
        return Response(status_code=404)
    return t


@app.delete("/api/transcript/{tid}")
async def delete_transcript(tid: int):
    db.delete_transcript(tid)
    return {"ok": True}


# ── API — Recherche ───────────────────────────────────────────────────────────
@app.get("/api/search")
async def search(q: str):
    return db.search_transcripts(q)


# ── API — Export ──────────────────────────────────────────────────────────────
@app.get("/api/transcript/{tid}/export/{fmt}")
async def export(tid: int, fmt: str):
    t = db.get_transcript(tid)
    if not t:
        return Response(status_code=404)

    name = (t.get("title") or t.get("video_id") or str(tid))[:60]
    name = "".join(c for c in name if c.isalnum() or c in " _-").strip()

    if fmt == "txt":
        return Response(
            export_txt(t["full_text"]),
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{name}.txt"'},
        )
    elif fmt == "srt":
        return Response(
            export_srt(t["segments"]),
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{name}.srt"'},
        )
    elif fmt == "json":
        return Response(
            export_json(t),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{name}.json"'},
        )
    return Response(status_code=400)
