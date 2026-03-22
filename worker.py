"""
worker.py — File d'attente d'extraction de sous-titres YouTube.
"""

import asyncio
import json as _json
import queue
import re
import threading
import urllib.request
from dataclasses import dataclass

import yt_dlp

from database import save_transcript


@dataclass
class Job:
    job_id: str
    url: str
    title: str = ""
    channel: str = ""
    video_id: str = ""
    status: str = "pending"  # pending | fetching | done | error
    progress_msg: str = ""
    error: str = ""
    transcript_id: int | None = None


# ── State global ──────────────────────────────────────────────────────────────

_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()

_job_queue: queue.Queue = queue.Queue()
_update_queue: asyncio.Queue | None = None

_PREFERRED_LANGS = ["fr", "en"]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "*/*",
    "Referer": "https://www.youtube.com/",
    "Origin": "https://www.youtube.com",
}


# ── Setup ─────────────────────────────────────────────────────────────────────


def set_update_queue(q: asyncio.Queue):
    global _update_queue
    _update_queue = q


def _push(job: Job):
    if _update_queue:
        _update_queue.put_nowait(
            {
                "job_id": job.job_id,
                "status": job.status,
                "msg": job.progress_msg,
                "title": job.title,
                "error": job.error,
                "transcript_id": job.transcript_id,
            }
        )


# ── Worker thread ─────────────────────────────────────────────────────────────


def _worker_loop():
    while True:
        job = _job_queue.get()
        try:
            _run_job(job)
        finally:
            _job_queue.task_done()


_worker_thread = threading.Thread(target=_worker_loop, daemon=True)
_worker_thread.start()


# ── API publique ──────────────────────────────────────────────────────────────


def get_all_jobs() -> list[dict]:
    with _jobs_lock:
        return [
            {
                "job_id": j.job_id,
                "title": j.title or j.url,
                "status": j.status,
                "msg": j.progress_msg,
                "error": j.error,
                "transcript_id": j.transcript_id,
            }
            for j in _jobs.values()
        ]


def enqueue(job: Job):
    with _jobs_lock:
        _jobs[job.job_id] = job
    _push(job)
    _job_queue.put(job)


# ── Pipeline d'un job ─────────────────────────────────────────────────────────


def _run_job(job: Job):
    try:
        job.status = "fetching"
        job.progress_msg = "Récupération des métadonnées…"
        _push(job)

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(job.url, download=False)

        job.title = info.get("title", job.url)
        job.channel = info.get("uploader", "")
        job.video_id = info.get("id", "")
        job.progress_msg = "Récupération des sous-titres…"
        _push(job)

        sub_url, sub_lang = _pick_subtitle(info)
        if not sub_url:
            raise ValueError("Aucun sous-titre disponible pour cette vidéo.")

        req = urllib.request.Request(sub_url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = _json.loads(r.read())

        result = _parse_json3(raw, sub_lang)
        if not result:
            raise ValueError("Sous-titres vides ou illisibles.")

        duration = result["segments"][-1]["end"] if result["segments"] else 0
        tid = save_transcript(
            {
                "video_id": job.video_id,
                "title": job.title,
                "channel": job.channel,
                "url": job.url,
                "full_text": result["text"],
                "segments": result["segments"],
                "duration": duration,
            }
        )

        job.status = "done"
        job.transcript_id = tid
        job.progress_msg = f"Terminé · {len(result['text'].split())} mots"
        _push(job)

    except Exception as e:
        job.status = "error"
        job.error = str(e)
        job.progress_msg = ""
        _push(job)


# ── Sélection et parsing des sous-titres ─────────────────────────────────────


def _pick_subtitle(info: dict) -> tuple[str | None, str | None]:
    """Retourne (url_json3, lang) — manuels > automatiques, fr > en > premier dispo."""
    for source in (info.get("subtitles", {}), info.get("automatic_captions", {})):
        for lang in _PREFERRED_LANGS:
            result = _get_json3_url(source, lang)
            if result:
                return result
        for lang in source:
            result = _get_json3_url(source, lang)
            if result:
                return result
    return None, None


def _get_json3_url(source: dict, lang: str) -> tuple[str, str] | None:
    entry = next((e for e in source.get(lang, []) if e.get("ext") == "json3"), None)
    if entry and entry.get("url"):
        return entry["url"], lang
    return None


def _parse_json3(raw: dict, lang: str) -> dict | None:
    segments = []
    full_parts = []

    for event in raw.get("events", []):
        if "segs" not in event:
            continue
        start = event["tStartMs"] / 1000
        dur = event.get("dDurationMs", 0) / 1000
        text = "".join(s.get("utf8", "") for s in event["segs"]).strip()
        text = re.sub(r"\s+", " ", text)
        if not text or text == "\n":
            continue
        segments.append({"start": start, "end": start + dur, "text": text})
        full_parts.append(text)

    if not segments:
        return None

    return {"text": " ".join(full_parts), "segments": segments, "language": lang}


# ── Récupération des vidéos d'une chaîne ─────────────────────────────────────


def fetch_channel_videos(channel_url: str) -> list[dict]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": 200,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    flat = []
    for e in info.get("entries", []):
        if not e:
            continue
        if e.get("_type") == "playlist" or not e.get("id"):
            flat.extend(sub for sub in e.get("entries", []) if sub)
        else:
            flat.append(e)

    videos = []
    seen = set()
    for e in flat:
        vid_id = e.get("id", "")
        if not vid_id or vid_id in seen:
            continue
        duration = e.get("duration")
        if duration is not None and duration <= 60:
            continue
        seen.add(vid_id)
        videos.append(
            {
                "id": vid_id,
                "title": e.get("title", "Sans titre"),
                "url": f"https://www.youtube.com/watch?v={vid_id}",
                "duration": duration,
                "thumbnail": e.get("thumbnail", ""),
                "upload_date": e.get("upload_date", ""),
            }
        )
    return videos
