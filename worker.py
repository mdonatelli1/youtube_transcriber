"""
worker.py — File d'attente de transcription (un seul job actif à la fois).
Les jobs sont traités séquentiellement via une queue threading.Queue.
La progression est poussée via une queue asyncio vers les WebSockets.
"""

import asyncio
import queue
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


# ── State global ──────────────────────────────────────────────────────────────

_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()

# File d'attente FIFO — un seul worker thread la consomme
_job_queue: queue.Queue = queue.Queue()

# Queue asyncio pour pousser les mises à jour vers les WebSockets
_update_queue: asyncio.Queue | None = None


# ── Setup ─────────────────────────────────────────────────────────────────────


def set_update_queue(q: asyncio.Queue):
    global _update_queue
    _update_queue = q


def _push(job: Job):
    """Envoie une mise à jour dans la queue asyncio (thread-safe)."""
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


# ── Worker thread (tourne en continu, traite un job à la fois) ───────────────


def _worker_loop():
    while True:
        job = _job_queue.get()  # bloquant jusqu'au prochain job
        try:
            _run_job(job)
        finally:
            _job_queue.task_done()


# Démarrage du thread unique au chargement du module
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
    """Ajoute un job en file — il sera traité dès que le worker est libre."""
    with _jobs_lock:
        _jobs[job.job_id] = job
    _push(job)
    _job_queue.put(job)


# ── Pipeline d'un job ─────────────────────────────────────────────────────────


def _run_job(job: Job):
    try:
        # 1. Métadonnées
        job.status = "downloading"
        job.progress_msg = "Récupération des métadonnées…"
        _push(job)

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(job.url, download=False)
            job.title = info.get("title", job.url)
            job.channel = info.get("uploader", "")
            job.video_id = info.get("id", "")
        _push(job)

        # 2. Téléchargement
        job.progress_msg = "Téléchargement de l'audio…"
        _push(job)
        audio_path = download_audio(job.url)

        # 3. Transcription
        job.status = "transcribing"
        job.progress_msg = "Transcription en cours…"
        _push(job)

        result = transcribe_audio(
            audio_path, model_size=job.model, language=job.language
        )
        audio_path.unlink(missing_ok=True)

        # 4. Sauvegarde
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


# ── Récupération des vidéos d'une chaîne ─────────────────────────────────────


def fetch_channel_videos(channel_url: str) -> list[dict]:
    """
    Retourne la liste des vidéos d'une chaîne YouTube.
    Gère le cas où YouTube retourne des sous-playlists (Videos, Shorts…)
    en ne gardant que les vraies vidéos (durée > 60s).
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

    # Descend dans les sous-playlists si nécessaire (Videos, Shorts, Live…)
    flat = []
    for e in raw_entries:
        if not e:
            continue
        if e.get("_type") == "playlist" or not e.get("id"):
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
