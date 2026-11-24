import sqlite3
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from .config import settings


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    if path != ":memory:":
        Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    with get_connection(db_path) as conn:
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id);")
        conn.commit()


def check_db_health(db_path: Optional[str] = None) -> bool:
    try:
        with get_connection(db_path) as conn:
            row = conn.execute("SELECT 1;").fetchone()
            return row is not None and row[0] == 1
    except Exception:
        return False


def get_effective_system_prompt(conn: sqlite3.Connection, session_id: str, requested_prompt: Optional[str]) -> str:
    # Use requested prompt, existing session prompt, or default
    if requested_prompt and requested_prompt.strip():
        return requested_prompt.strip()
    row = conn.execute("SELECT system_prompt FROM sessions WHERE session_id = ?;", (session_id,)).fetchone()
    if row and row["system_prompt"]:
        return row["system_prompt"]
    return settings.default_system_prompt


def get_conversation_history(conn: sqlite3.Connection, session_id: str) -> List[Dict[str, str]]:
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC;",
        (session_id,)
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def get_session_messages_for_api(conn: sqlite3.Connection, session_id: str) -> Optional[List[Dict[str, Any]]]:
    # Return 404 signal (None) if session was never created
    if not conn.execute("SELECT 1 FROM sessions WHERE session_id = ?;", (session_id,)).fetchone():
        return None

    rows = conn.execute(
        "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id ASC;",
        (session_id,)
    ).fetchall()

    results = []
    for r in rows:
        meta = json.loads(r["metadata"]) if r["metadata"] else None
        item = {"role": r["role"], "content": r["content"]}
        if meta is not None:
            item["metadata"] = meta
        results.append(item)
    return results


def persist_turn(
    conn: sqlite3.Connection,
    session_id: str,
    system_prompt: str,
    user_msg: str,
    assistant_reply: str,
    metadata: Dict[str, Any]
) -> None:
    # Save conversation turn atomically only after successful reply
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO sessions (session_id, system_prompt, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET system_prompt = excluded.system_prompt;
    """, (session_id, system_prompt, now))

    cursor.execute(
        "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?);",
        (session_id, "user", user_msg, None, now)
    )
    cursor.execute(
        "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?);",
        (session_id, "assistant", assistant_reply, json.dumps(metadata), now)
    )
    conn.commit()
