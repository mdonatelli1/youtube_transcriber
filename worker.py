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
    Gère le cas où YouTube retourne des sous-playlists (Videos, Shorts…)
    en ne gardant que les vraies vidéos (durée > 0, pas les Shorts).
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": 200,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    raw_entries = info.get("entries", [])

    # YouTube renvoie parfois des sous-playlists (Videos, Shorts, Live…)
    # On descend d'un niveau si les entrées sont elles-mêmes des playlists
    flat = []
    for e in raw_entries:
        if not e:
            continue
        if e.get("_type") == "playlist" or not e.get("id"):
            # C'est une sous-playlist — on prend ses entrées si disponibles
            for sub in e.get("entries", []):
                if sub:
                    flat.append(sub)
        else:
            flat.append(e)

    videos = []
    seen = set()
    for e in flat:
        vid_id = e.get("id", "")
        if not vid_id or vid_id in seen:
            continue
        # Exclure les Shorts (durée <= 60s quand disponible)
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
