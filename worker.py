"""
worker.py — File d'attente de transcription.
Chaque job tourne dans un thread séparé et envoie sa progression
via une queue asyncio que FastAPI lit via WebSocket.
"""

import asyncio
import threading
from dataclasses import dataclass

import yt_dlp

from database import save_transcript
from downloader import download_audio
from transcriber import transcribe_audio


@dataclass
class Job:
    job_id: str
    url: str
    title: str = ""
    channel: str = ""
    video_id: str = ""
    model: str = "small"
    language: str | None = None
    status: str = "pending"  # pending | downloading | transcribing | done | error
    progress_msg: str = ""
    error: str = ""
    transcript_id: int | None = None


# File globale des jobs (accessible depuis main.py)
_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()

# Queue asyncio pour pousser les mises à jour vers les WebSockets
_update_queue: asyncio.Queue | None = None


def set_update_queue(q: asyncio.Queue):
    global _update_queue
    _update_queue = q


def _push(job: Job):
    """Envoie une mise à jour de job dans la queue asyncio (thread-safe)."""
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
    t = threading.Thread(target=_run_job, args=(job,), daemon=True)
    t.start()


def _run_job(job: Job):
    try:
        # ── 1. Fetch metadata ────────────────────────────────────────────────
        job.status = "downloading"
        job.progress_msg = "Récupération des métadonnées…"
        _push(job)

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(job.url, download=False)
            job.title = info.get("title", job.url)
            job.channel = info.get("uploader", "")
            job.video_id = info.get("id", "")
        _push(job)

        # ── 2. Download ──────────────────────────────────────────────────────
        job.progress_msg = "Téléchargement de l'audio…"
        _push(job)
        audio_path = download_audio(job.url)

        # ── 3. Transcribe ────────────────────────────────────────────────────
        job.status = "transcribing"
        job.progress_msg = "Transcription en cours…"
        _push(job)

        result = transcribe_audio(
            audio_path, model_size=job.model, language=job.language
        )
        audio_path.unlink(missing_ok=True)

        # ── 4. Save ──────────────────────────────────────────────────────────
        duration = result["segments"][-1]["end"] if result["segments"] else 0
        tid = save_transcript(
            {
                "video_id": job.video_id,
                "title": job.title,
                "channel": job.channel,
                "url": job.url,
                "language": result.get("language", ""),
                "model": job.model,
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


# ── Récupération des vidéos d'une chaîne ────────────────────────────────────


def fetch_channel_videos(channel_url: str) -> list[dict]:
    """
    Retourne la liste des vidéos d'une chaîne YouTube.
    Chaque entrée : {id, title, url, duration, thumbnail, upload_date}
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,  # Ne télécharge pas, récupère juste la liste
        "playlistend": 200,  # Max 200 vidéos
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    entries = info.get("entries", [])
    videos = []
    for e in entries:
        if not e:
            continue
        videos.append(
            {
                "id": e.get("id", ""),
                "title": e.get("title", "Sans titre"),
                "url": f"https://www.youtube.com/watch?v={e.get('id', '')}",
                "duration": e.get("duration"),
                "thumbnail": e.get("thumbnail", ""),
                "upload_date": e.get("upload_date", ""),
            }
        )
    return videos
