from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .conversation_models import initial_analysis_state, merge_state


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    selected_provider TEXT NOT NULL,
    selected_model TEXT NOT NULL,
    conversation_summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    legacy_session_id TEXT UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    status TEXT NOT NULL,
    error_code TEXT,
    artifact_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_states (
    conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_files (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    dataset_id TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    added_at TEXT NOT NULL,
    PRIMARY KEY(conversation_id, dataset_id)
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_conversation_created ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS artifacts_conversation_created ON artifacts(conversation_id, created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationStore:
    def __init__(self, database_path: Path, legacy_root: Path | None = None):
        self.database_path = database_path
        self.legacy_root = legacy_root
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def create_conversation(self, title: str, provider: str, model: str, file_ids: list[str] | None = None) -> dict:
        conversation_id = str(uuid4())
        timestamp = _now()
        ids = list(dict.fromkeys(file_ids or []))
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, '', 'active', NULL, ?, ?)",
                (conversation_id, title, provider, model, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO analysis_states VALUES (?, ?, ?)",
                (conversation_id, json.dumps(initial_analysis_state(ids), ensure_ascii=False), timestamp),
            )
            connection.executemany(
                "INSERT INTO conversation_files VALUES (?, ?, 1, ?)",
                [(conversation_id, file_id, timestamp) for file_id in ids],
            )
        return self.get_conversation(conversation_id)

    def list_conversations(self, offset: int = 0, limit: int = 100) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
            return [self._conversation(connection, row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            if row is None:
                raise KeyError(conversation_id)
            return self._conversation(connection, row)

    def _conversation(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
        files = connection.execute(
            "SELECT dataset_id FROM conversation_files WHERE conversation_id = ? ORDER BY added_at", (row["id"],)
        ).fetchall()
        return {
            "id": row["id"],
            "title": row["title"],
            "selected_provider": row["selected_provider"],
            "selected_model": row["selected_model"],
            "conversation_summary": row["conversation_summary"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "file_ids": [item["dataset_id"] for item in files],
        }

    def update_model(self, conversation_id: str, provider: str, model: str) -> dict:
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE conversations SET selected_provider = ?, selected_model = ?, updated_at = ? WHERE id = ?",
                (provider, model, _now(), conversation_id),
            ).rowcount
            if not updated:
                raise KeyError(conversation_id)
        return self.get_conversation(conversation_id)

    def update_summary(self, conversation_id: str, summary: str) -> None:
        with self._connect() as connection:
            if not connection.execute(
                "UPDATE conversations SET conversation_summary = ?, updated_at = ? WHERE id = ?", (summary, _now(), conversation_id)
            ).rowcount:
                raise KeyError(conversation_id)

    def list_messages(self, conversation_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at, id", (conversation_id,)
            ).fetchall()
        return [self._message(row) for row in rows]

    def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        provider: str | None = None,
        model: str | None = None,
        status: str = "completed",
        error_code: str | None = None,
    ) -> dict:
        message_id = str(uuid4())
        timestamp = _now()
        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone() is None:
                raise KeyError(conversation_id)
            connection.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', ?)",
                (message_id, conversation_id, role, content, provider, model, status, error_code, timestamp),
            )
            connection.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (timestamp, conversation_id))
            row = connection.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        return self._message(row)

    def _message(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"], "conversation_id": row["conversation_id"], "role": row["role"], "content": row["content"],
            "provider": row["provider"], "model": row["model"], "status": row["status"], "error_code": row["error_code"],
            "artifact_ids": json.loads(row["artifact_ids_json"]), "created_at": row["created_at"],
        }

    def get_analysis_state(self, conversation_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute("SELECT state_json FROM analysis_states WHERE conversation_id = ?", (conversation_id,)).fetchone()
            if row is None:
                raise KeyError(conversation_id)
            return json.loads(row["state_json"])

    def merge_analysis_state(self, conversation_id: str, patch: dict) -> dict:
        current = self.get_analysis_state(conversation_id)
        state = merge_state(current, patch)
        with self._connect() as connection:
            if not connection.execute(
                "UPDATE analysis_states SET state_json = ?, updated_at = ? WHERE conversation_id = ?",
                (json.dumps(state, ensure_ascii=False), _now(), conversation_id),
            ).rowcount:
                raise KeyError(conversation_id)
        return state

    def add_artifact(self, conversation_id: str, message_id: str | None, kind: str, relative_path: str, metadata: dict | None = None) -> dict:
        artifact_id = str(uuid4())
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (artifact_id, conversation_id, message_id, kind, relative_path, json.dumps(metadata or {}, ensure_ascii=False), timestamp),
            )
            if message_id:
                row = connection.execute("SELECT artifact_ids_json FROM messages WHERE id = ?", (message_id,)).fetchone()
                if row:
                    ids = [*json.loads(row["artifact_ids_json"]), artifact_id]
                    connection.execute("UPDATE messages SET artifact_ids_json = ? WHERE id = ?", (json.dumps(ids), message_id))
        return {"id": artifact_id, "conversation_id": conversation_id, "message_id": message_id, "kind": kind, "relative_path": relative_path, "metadata": metadata or {}, "created_at": timestamp}

    def list_artifacts(self, conversation_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM artifacts WHERE conversation_id = ? ORDER BY created_at, id", (conversation_id,)).fetchall()
        return [{"id": row["id"], "conversation_id": row["conversation_id"], "message_id": row["message_id"], "kind": row["kind"], "relative_path": row["relative_path"], "metadata": json.loads(row["metadata_json"]), "created_at": row["created_at"]} for row in rows]

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._connect() as connection:
            return bool(connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,)).rowcount)

    def clear_conversations(self) -> int:
        with self._connect() as connection:
            return connection.execute("DELETE FROM conversations").rowcount

    def migrate_legacy_sessions(self) -> int:
        if self.legacy_root is None:
            return 0
        imported = 0
        for path in (self.legacy_root / "sessions").glob("*/session.json") if (self.legacy_root / "sessions").exists() else []:
            session = json.loads(path.read_text(encoding="utf-8"))
            session_id = str(session.get("id", ""))
            if not session_id:
                continue
            with self._connect() as connection:
                if connection.execute("SELECT 1 FROM conversations WHERE legacy_session_id = ?", (session_id,)).fetchone():
                    continue
                created = str(session.get("created_at") or _now())
                updated = str(session.get("updated_at") or created)
                connection.execute(
                    "INSERT INTO conversations VALUES (?, ?, 'simulated', 'analysis-sim', '', 'active', ?, ?, ?)",
                    (session_id, str(session.get("title") or "历史分析"), session_id, created, updated),
                )
                file_ids = [str(session["dataset_id"])] if session.get("dataset_id") else []
                connection.execute(
                    "INSERT INTO analysis_states VALUES (?, ?, ?)",
                    (session_id, json.dumps(initial_analysis_state(file_ids), ensure_ascii=False), updated),
                )
                connection.executemany(
                    "INSERT INTO conversation_files VALUES (?, ?, 1, ?)", [(session_id, file_id, created) for file_id in file_ids]
                )
                for item in session.get("messages", []):
                    connection.execute(
                        "INSERT INTO messages VALUES (?, ?, ?, ?, NULL, NULL, 'completed', NULL, '[]', ?)",
                        (str(uuid4()), session_id, str(item.get("role", "assistant")), str(item.get("content", "")), str(item.get("created_at") or created)),
                    )
                imported += 1
        return imported
