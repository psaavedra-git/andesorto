"""Consulta la base del bot (solo lectura).

Uso:
  python scripts/sql.py "SELECT * FROM orders"
  python scripts/sql.py pedidos | conversaciones | chat 51999888777 | pausados | tablas
  python scripts/sql.py "SELECT ..." --csv salida.csv
"""
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.config import BASE_DIR, get_settings  # noqa: E402

SHORTCUTS = {
    "tablas": "SELECT name FROM sqlite_master WHERE type = 'table'",
    "pedidos": "SELECT code, tipo, wa_id, datetime(ts, 'unixepoch', 'localtime') AS fecha, data FROM orders ORDER BY id DESC",
    "conversaciones": (
        "SELECT wa_id, COUNT(*) AS mensajes, datetime(MAX(ts), 'unixepoch', 'localtime') AS ultimo "
        "FROM messages GROUP BY wa_id ORDER BY MAX(ts) DESC"
    ),
    "pausados": (
        "SELECT wa_id, paused_reason, datetime(paused_at, 'unixepoch', 'localtime') AS desde "
        "FROM conversations WHERE paused = 1"
    ),
}


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    csv_path = None
    if "--csv" in args:
        i = args.index("--csv")
        csv_path = args[i + 1]
        args = args[:i] + args[i + 2 :]

    params: tuple = ()
    if args[0] == "chat" and len(args) > 1:
        query = (
            "SELECT datetime(ts, 'unixepoch', 'localtime') AS fecha, role, content "
            "FROM messages WHERE wa_id = ? ORDER BY id"
        )
        params = (args[1],)
    else:
        query = SHORTCUTS.get(args[0], args[0])

    db = Path(get_settings().db_path)
    if not db.is_absolute():
        db = BASE_DIR / db
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        cur = conn.execute(query, params)
    except sqlite3.Error as exc:
        sys.exit(f"Error: {exc}")
    cols = [d[0] for d in cur.description or []]
    rows = cur.fetchall()

    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel abre bien los acentos
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        print(f"{len(rows)} filas → {csv_path}")
        return

    cells = [[("" if v is None else str(v)).replace("\n", " ⏎ ")[:80] for v in r] for r in rows]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(cols)]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in cells:
        print("  ".join(v.ljust(w) for v, w in zip(r, widths)))
    print(f"\n({len(rows)} filas)")


if __name__ == "__main__":
    main()
