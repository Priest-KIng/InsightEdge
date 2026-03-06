from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.schemas import ChatTurn


class StateStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    PRIMARY KEY (session_id, turn_index)
                )
                """,
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingest_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    files_total INTEGER NOT NULL DEFAULT 0,
                    files_processed INTEGER NOT NULL DEFAULT 0,
                    chunks_indexed INTEGER NOT NULL DEFAULT 0,
                    skipped_files INTEGER NOT NULL DEFAULT 0,
                    error TEXT
                )
                """,
            )
            conn.commit()

    def get_chat_history(self, session_id: str) -> list[ChatTurn]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content
                FROM chat_sessions
                WHERE session_id = ?
                ORDER BY turn_index ASC
                """,
                (session_id,),
            ).fetchall()
        return [ChatTurn(role=str(row["role"]), content=str(row["content"])) for row in rows]

    def set_chat_history(self, session_id: str, history: list[ChatTurn]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
            conn.executemany(
                """
                INSERT INTO chat_sessions (session_id, turn_index, role, content)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (session_id, idx, turn.role, turn.content)
                    for idx, turn in enumerate(history)
                ],
            )
            conn.commit()

    def clear_chat_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
            conn.commit()

    def create_ingest_job(self, job_id: str, files_total: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_jobs (
                    job_id, status, files_total, files_processed, chunks_indexed, skipped_files, error
                )
                VALUES (?, 'queued', ?, 0, 0, 0, NULL)
                """,
                (job_id, files_total),
            )
            conn.commit()

    def update_ingest_job(self, job_id: str, **updates: str | int | None) -> None:
        if not updates:
            return
        fields = ", ".join(f"{key} = ?" for key in updates)
        values: list[Any] = [updates[key] for key in updates]
        values.append(job_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE ingest_jobs SET {fields} WHERE job_id = ?", values)
            conn.commit()

    def get_ingest_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT job_id, status, files_total, files_processed, chunks_indexed, skipped_files, error
                FROM ingest_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)


