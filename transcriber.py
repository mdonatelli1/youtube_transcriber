"""
transcriber.py — Transcription audio avec faster-whisper.
Utilise le GPU (CUDA) automatiquement si disponible, sinon CPU.
Le modèle est chargé une seule fois grâce à @st.cache_resource.
"""

from pathlib import Path

import torch
from faster_whisper import WhisperModel


def _load_model(model_size: str) -> WhisperModel:
    """
    Charge le modèle une seule fois et le garde en mémoire (cache Streamlit).
    Rechargé uniquement si model_size change.
    """
    if torch.cuda.is_available():
        device = "cuda"
        compute_type = "float16"  # float16 = rapide sur GPU
    else:
        device = "cpu"
        compute_type = "int8"  # int8 = bon compromis vitesse/précision sur CPU

    return WhisperModel(model_size, device=device, compute_type=compute_type)


def transcribe_audio(
    audio_path: Path,
    model_size: str = "small",
    language: str | None = None,
) -> dict:
    """
    Transcrit le fichier audio avec faster-whisper.

    Args:
        audio_path:  Chemin vers le fichier .wav
        model_size:  tiny | base | small | medium | large-v3
        language:    Code ISO 639-1 (ex: "fr", "en") ou None pour auto-détection

    Returns:
        dict avec les clés :
          - "text"      : texte complet
          - "segments"  : liste de dicts {start, end, text}
          - "language"  : langue détectée
    """
    model = _load_model(model_size)

    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
        vad_filter=True,  # Filtre les silences automatiquement
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    segments = []
    full_text_parts = []

    for seg in segments_iter:
        segments.append(
            {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
            }
        )
        full_text_parts.append(seg.text.strip())

    return {
        "text": " ".join(full_text_parts),
        "segments": segments,
        "language": info.language,
    }
