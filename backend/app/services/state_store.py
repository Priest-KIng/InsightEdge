from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.config import settings
from app.schemas import ChatTurn


class StateStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    turn_index INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT,
                    PRIMARY KEY (session_id, workspace_id, turn_index)
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
                    error TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """,
            )
            has_workspace_column = conn.execute(
                """
                SELECT COUNT(1)
                FROM pragma_table_info('chat_sessions')
                WHERE name = 'workspace_id'
                """,
            ).fetchone()[0]
            if not has_workspace_column:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_sessions_new (
                        session_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL DEFAULT 'default',
                        turn_index INTEGER NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT,
                        PRIMARY KEY (session_id, workspace_id, turn_index)
                    )
                    """,
                )
                conn.execute(
                    """
                    INSERT INTO chat_sessions_new (session_id, workspace_id, turn_index, role, content, created_at)
                    SELECT session_id, 'default', turn_index, role, content, datetime('now')
                    FROM chat_sessions
                    """,
                )
                conn.execute("DROP TABLE chat_sessions")
                conn.execute("ALTER TABLE chat_sessions_new RENAME TO chat_sessions")
            self._ensure_column(conn, "chat_sessions", "created_at", "TEXT")
            self._ensure_column(conn, "ingest_jobs", "created_at", "TEXT")
            self._ensure_column(conn, "ingest_jobs", "updated_at", "TEXT")
            conn.execute(
                "UPDATE chat_sessions SET created_at = COALESCE(created_at, datetime('now'))"
            )
            conn.execute(
                "UPDATE ingest_jobs SET created_at = COALESCE(created_at, datetime('now')), "
                "updated_at = COALESCE(updated_at, created_at, datetime('now'))"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_sessions_workspace ON chat_sessions(workspace_id, session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status ON ingest_jobs(status, updated_at)"
            )
            conn.commit()

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        exists = conn.execute(
            f"SELECT COUNT(1) FROM pragma_table_info('{table}') WHERE name = ?",
            (column,),
        ).fetchone()[0]
        if not exists:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def get_chat_history(self, session_id: str, workspace_id: str | None = None) -> list[ChatTurn]:
        resolved_workspace = workspace_id or settings.default_workspace_id
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content
                    , created_at
                FROM chat_sessions
                WHERE session_id = ? AND workspace_id = ?
                ORDER BY turn_index ASC
                """,
                (session_id, resolved_workspace),
            ).fetchall()
        return [
            ChatTurn(
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]) if row["created_at"] else None,
            )
            for row in rows
        ]

    def set_chat_history(
        self,
        session_id: str,
        history: list[ChatTurn],
        workspace_id: str | None = None,
    ) -> None:
        resolved_workspace = workspace_id or settings.default_workspace_id
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM chat_sessions WHERE session_id = ? AND workspace_id = ?",
                (session_id, resolved_workspace),
            )
            conn.executemany(
                """
                INSERT INTO chat_sessions (session_id, workspace_id, turn_index, role, content, created_at)
                VALUES (?, ?, ?, ?, ?, COALESCE(?, datetime('now')))
                """,
                [
                    (session_id, resolved_workspace, idx, turn.role, turn.content, turn.created_at)
                    for idx, turn in enumerate(history)
                ],
            )
            conn.commit()

    def clear_chat_session(self, session_id: str, workspace_id: str | None = None) -> None:
        resolved_workspace = workspace_id or settings.default_workspace_id
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM chat_sessions WHERE session_id = ? AND workspace_id = ?",
                (session_id, resolved_workspace),
            )
            conn.commit()

    def create_ingest_job(self, job_id: str, files_total: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_jobs (
                    job_id, status, files_total, files_processed, chunks_indexed, skipped_files, error, created_at, updated_at
                )
                VALUES (?, 'queued', ?, 0, 0, 0, NULL, datetime('now'), datetime('now'))
                """,
                (job_id, files_total),
            )
            conn.commit()

    def update_ingest_job(self, job_id: str, **updates: str | int | None) -> None:
        if not updates:
            return
        allowed_fields = {"status", "files_processed", "chunks_indexed", "skipped_files", "error"}
        safe_updates = {key: value for key, value in updates.items() if key in allowed_fields}
        if not safe_updates:
            return
        fields = ", ".join(f"{key} = ?" for key in safe_updates)
        values: list[Any] = [safe_updates[key] for key in safe_updates]
        values.append(job_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE ingest_jobs SET {fields}, updated_at = datetime('now') WHERE job_id = ?",
                values,
            )
            conn.commit()

    def get_ingest_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT job_id, status, files_total, files_processed, chunks_indexed, skipped_files, error, created_at, updated_at
                FROM ingest_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def clear_workspace(self, workspace_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM chat_sessions WHERE workspace_id = ?", (workspace_id,))
            conn.commit()


