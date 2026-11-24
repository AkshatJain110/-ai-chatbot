import sqlite3
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone

from .config import settings

def get_db_path(url: Optional[str] = None) -> str:
    db_url = url or settings.database_url
    if db_url.startswith("sqlite:///"):
        path = db_url[len("sqlite:///"):]
    else:
        path = db_url
    return path

def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = get_db_path(db_path)
    if path != ":memory:":
        Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn

def init_db(db_path: Optional[str] = None) -> None:
    path = get_db_path(db_path)
    if path != ":memory:":
        Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)

    with get_connection(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                system_prompt TEXT,
                created_at TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id);
        """)
        conn.commit()

def check_db_health(db_path: Optional[str] = None) -> bool:
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1;")
            row = cursor.fetchone()
            return row is not None and row[0] == 1
    except Exception:
        return False

def get_effective_system_prompt(
    conn: sqlite3.Connection,
    session_id: str,
    requested_system_prompt: Optional[str] = None
) -> str:
    """
    Computes effective system prompt without writing to database.
    If requested_system_prompt is provided, it overrides.
    Otherwise uses existing session prompt, or default_system_prompt.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT system_prompt FROM sessions WHERE session_id = ?;", (session_id,))
    row = cursor.fetchone()

    if requested_system_prompt is not None and requested_system_prompt.strip() != "":
        return requested_system_prompt.strip()
    elif row is not None and row["system_prompt"]:
        return row["system_prompt"]
    else:
        return settings.default_system_prompt

def get_conversation_history(conn: sqlite3.Connection, session_id: str) -> List[Dict[str, str]]:
    """
    Returns message history for feeding into LLM in chronological order.
    Format: [{'role': 'user', 'content': '...'}, {'role': 'assistant', 'content': '...'}]
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC;",
        (session_id,)
    )
    rows = cursor.fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]

def get_session_messages_for_api(conn: sqlite3.Connection, session_id: str) -> Optional[List[Dict[str, Any]]]:
    """
    Returns messages for the GET /sessions/{session_id}/messages endpoint.
    Returns None if the session does not exist.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT session_id FROM sessions WHERE session_id = ?;", (session_id,))
    session_row = cursor.fetchone()

    if session_row is None:
        return None

    cursor.execute(
        "SELECT role, content, metadata, created_at FROM messages WHERE session_id = ? ORDER BY id ASC;",
        (session_id,)
    )
    message_rows = cursor.fetchall()

    results = []
    for row in message_rows:
        meta = None
        if row["metadata"]:
            try:
                meta = json.loads(row["metadata"])
            except Exception:
                meta = None
        item: Dict[str, Any] = {
            "role": row["role"],
            "content": row["content"]
        }
        if meta is not None:
            item["metadata"] = meta
        results.append(item)
    return results

def persist_turn(
    conn: sqlite3.Connection,
    session_id: str,
    system_prompt: str,
    user_content: str,
    assistant_content: str,
    assistant_metadata: Dict[str, Any]
) -> None:
    """
    Atomically creates or updates session and writes user + assistant messages.
    Called ONLY AFTER a successful reply.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor = conn.cursor()

    # Upsert session
    cursor.execute("SELECT session_id FROM sessions WHERE session_id = ?;", (session_id,))
    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO sessions (session_id, system_prompt, created_at) VALUES (?, ?, ?);",
            (session_id, system_prompt, now_iso)
        )
    else:
        cursor.execute(
            "UPDATE sessions SET system_prompt = ? WHERE session_id = ?;",
            (system_prompt, session_id)
        )

    # Insert user and assistant messages
    cursor.execute(
        "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?);",
        (session_id, "user", user_content, None, now_iso)
    )
    cursor.execute(
        "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?);",
        (session_id, "assistant", assistant_content, json.dumps(assistant_metadata), now_iso)
    )
    conn.commit()
