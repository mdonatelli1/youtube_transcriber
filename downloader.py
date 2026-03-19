"""
downloader.py — Télécharge l'audio d'une vidéo YouTube via yt-dlp.
Retourne le chemin vers le fichier audio temporaire.
"""

import tempfile
from pathlib import Path

import yt_dlp


def download_audio(url: str) -> Path:
    """
    Télécharge l'audio de la vidéo YouTube pointée par `url`.
    Retourne un Path vers le fichier audio .wav (16kHz mono),
    prêt pour Whisper.
    """
    tmp_dir = Path(tempfile.mkdtemp())
    output_template = str(tmp_dir / "audio.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        # On demande directement un wav 16kHz mono via ffmpeg post-processor
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "0",
            }
        ],
        "postprocessor_args": [
            "-ar",
            "16000",  # 16 kHz — optimal pour Whisper
            "-ac",
            "1",  # mono
        ],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Le fichier résultant est toujours audio.wav après le postprocessor
    audio_path = tmp_dir / "audio.wav"
    if not audio_path.exists():
        raise FileNotFoundError(f"Le fichier audio n'a pas été créé dans {tmp_dir}")

    return audio_path
