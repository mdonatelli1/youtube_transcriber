# YouTube Transcriber v2

App web locale — FastAPI + Faster-Whisper.  
Transcription de vidéos individuelles ou de chaînes entières, historique, recherche plein-texte.

---

## Installation

### 1. Prérequis

- Python 3.10+
- FFmpeg installé et dans le PATH

### 2. Environnement virtuel

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Dépendances

```bash
pip install -r requirements.txt
```

### 4. Lancer le serveur

```bash
uvicorn main:app --reload
```

Ouvre **http://localhost:8000** dans ton navigateur.

---

## Structure

```
v2/
├── main.py          # Serveur FastAPI + WebSocket
├── worker.py        # File d'attente de transcription
├── database.py      # SQLite — historique & recherche FTS
├── downloader.py    # Téléchargement audio via yt-dlp
├── transcriber.py   # Transcription via faster-whisper
├── exporter.py      # Export .txt / .srt / .json
├── requirements.txt
└── static/
    ├── index.html   # Structure HTML uniquement
    ├── style.css    # Tout le CSS
    ├── app.js       # Toute la logique JS
    └── icons.svg    # Les symboles SVG
```

---

## Fonctionnalités

- **Vidéo unique** — colle une URL, lance la transcription
- **Chaîne entière** — charge la liste des vidéos, sélectionne, transcrit en batch
- **File d'attente** — suivi en temps réel via WebSocket
- **Historique** — toutes les transcriptions sauvegardées en SQLite
- **Recherche plein-texte** — recherche dans le contenu de toutes les transcriptions
- **Export** — .txt, .srt, .json par transcription
