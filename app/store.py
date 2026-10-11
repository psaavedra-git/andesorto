"""Persistencia en SQLite: historial, estado de pausa (derivación) y deduplicación."""
import json
import sqlite3
import threading
import time


class Store:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wa_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_messages_wa ON messages(wa_id, id);
                CREATE TABLE IF NOT EXISTS conversations (
                    wa_id TEXT PRIMARY KEY,
                    paused INTEGER NOT NULL DEFAULT 0,
                    paused_reason TEXT,
                    paused_at REAL
                );
                CREATE TABLE IF NOT EXISTS processed_ids (
                    id TEXT PRIMARY KEY,
                    ts REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT,
                    tipo TEXT NOT NULL,
                    wa_id TEXT,
                    data TEXT NOT NULL,
                    ts REAL NOT NULL
                );
                """
            )

    # --- dedupe ---
    def mark_processed(self, message_id: str) -> bool:
        """True si es la primera vez que vemos este id; False si es un reintento de Meta."""
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO processed_ids(id, ts) VALUES (?, ?)", (message_id, time.time())
            )
            self._conn.commit()
            return cur.rowcount == 1

    # --- historial ---
    def add_message(self, wa_id: str, role: str, content: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages(wa_id, role, content, ts) VALUES (?, ?, ?, ?)",
                (wa_id, role, content, time.time()),
            )
            self._conn.commit()

    def history(self, wa_id: str, limit: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM messages WHERE wa_id = ? ORDER BY id DESC LIMIT ?",
                (wa_id, limit),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    # --- pausa / derivación ---
    def pause(self, wa_id: str, reason: str) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO conversations(wa_id, paused, paused_reason, paused_at) VALUES (?, 1, ?, ?)
                   ON CONFLICT(wa_id) DO UPDATE SET paused = 1, paused_reason = excluded.paused_reason,
                   paused_at = excluded.paused_at""",
                (wa_id, reason, time.time()),
            )
            self._conn.commit()

    def resume(self, wa_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE conversations SET paused = 0, paused_reason = NULL, paused_at = NULL "
                "WHERE wa_id = ? AND paused = 1",
                (wa_id,),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def is_paused(self, wa_id: str, timeout_hours: float) -> bool:
        """Pausado y dentro del timeout. Si el timeout venció, reactiva el bot automáticamente."""
        with self._lock:
            row = self._conn.execute(
                "SELECT paused, paused_at FROM conversations WHERE wa_id = ?", (wa_id,)
            ).fetchone()
        if not row or not row["paused"]:
            return False
        if timeout_hours > 0 and time.time() - (row["paused_at"] or 0) > timeout_hours * 3600:
            self.resume(wa_id)
            return False
        return True

    # --- pedidos ---
    def add_order(self, tipo: str, wa_id: str | None, data: dict) -> str:
        """Guarda el pedido y devuelve su código, ej. AO-N-0007 (nuevo) o AO-R-0003 (reparación)."""
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO orders(tipo, wa_id, data, ts) VALUES (?, ?, ?, ?)",
                (tipo, wa_id, json.dumps(data, ensure_ascii=False), time.time()),
            )
            code = f"AO-{'N' if tipo == 'nuevo' else 'R'}-{cur.lastrowid:04d}"
            self._conn.execute("UPDATE orders SET code = ? WHERE id = ?", (code, cur.lastrowid))
            self._conn.commit()
        return code

    def paused_list(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT wa_id, paused_reason, paused_at FROM conversations WHERE paused = 1 ORDER BY paused_at"
            ).fetchall()
        return [dict(r) for r in rows]
