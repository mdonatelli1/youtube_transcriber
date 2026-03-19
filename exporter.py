"""
exporter.py — Génère les fichiers de sortie dans différents formats.
"""

import json


def export_txt(full_text: str) -> bytes:
    """Texte brut."""
    return full_text.encode("utf-8")


def export_srt(segments: list[dict]) -> bytes:
    """
    Format SRT standard pour sous-titres.
    Compatible VLC, YouTube, DaVinci Resolve, etc.
    """
    lines = []
    for i, seg in enumerate(segments, start=1):
        start = _srt_timestamp(seg["start"])
        end = _srt_timestamp(seg["end"])
        lines.append(f"{i}\n{start} --> {end}\n{seg['text'].strip()}\n")
    return "\n".join(lines).encode("utf-8")


def export_json(result: dict) -> bytes:
    """JSON complet avec texte, segments et langue détectée."""
    return json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")


def _srt_timestamp(seconds: float) -> str:
    """Convertit des secondes en format SRT : HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
