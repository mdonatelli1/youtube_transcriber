"""
database.py — Historique des transcriptions avec SQLite.
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("transcripts.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transcripts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id    TEXT NOT NULL,
                title       TEXT,
                channel     TEXT,
                url         TEXT,
                language    TEXT,
                model       TEXT,
                full_text   TEXT,
                segments    TEXT,       -- JSON
                duration    REAL,
                word_count  INTEGER,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts
            USING fts5(video_id, title, channel, full_text, content='transcripts', content_rowid='id')
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS transcripts_ai AFTER INSERT ON transcripts BEGIN
                INSERT INTO transcripts_fts(rowid, video_id, title, channel, full_text)
                VALUES (new.id, new.video_id, new.title, new.channel, new.full_text);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS transcripts_ad AFTER DELETE ON transcripts BEGIN
                INSERT INTO transcripts_fts(transcripts_fts, rowid, video_id, title, channel, full_text)
                VALUES ('delete', old.id, old.video_id, old.title, old.channel, old.full_text);
            END
        """)


def save_transcript(data: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO transcripts
                (video_id, title, channel, url, language, model, full_text, segments, duration, word_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                data["video_id"],
                data.get("title", ""),
                data.get("channel", ""),
                data.get("url", ""),
                data.get("language", ""),
                data.get("model", ""),
                data.get("full_text", ""),
                json.dumps(data.get("segments", []), ensure_ascii=False),
                data.get("duration", 0),
                len(data.get("full_text", "").split()),
            ),
        )
        return cur.lastrowid


def get_history(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, video_id, title, channel, url, language, model,
                   word_count, duration, created_at
            FROM transcripts
            ORDER BY created_at DESC
            LIMIT ?
        """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_transcript(transcript_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM transcripts WHERE id = ?", (transcript_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["segments"] = json.loads(d["segments"] or "[]")
    return d


def search_transcripts(query: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT t.id, t.video_id, t.title, t.channel, t.url,
                   t.language, t.word_count, t.created_at,
                   snippet(transcripts_fts, 3, '<mark>', '</mark>', '…', 20) AS snippet
            FROM transcripts_fts
            JOIN transcripts t ON t.id = transcripts_fts.rowid
            WHERE transcripts_fts MATCH ?
            ORDER BY rank
            LIMIT 30
        """,
            (query,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_transcript(transcript_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM transcripts WHERE id = ?", (transcript_id,))
