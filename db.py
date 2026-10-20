"""Storage: last refresh snapshot, manual warehouse choices, rate cache, comparison archive.

Local: SQLite file (DB_PATH). Server: PostgreSQL (e.g. Neon free plan) when DATABASE_URL is set.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

import config

ARCHIVE_COLUMNS = [
    "order_id", "order_number", "sku", "state", "postal", "assigned_wh",
    "ups_il", "ups_ca", "ups_tx", "fedex_il", "fedex_ca", "fedex_tx",
    "best_ups", "best_fedex", "cheapest_carrier", "cheapest_wh", "cheapest_rate",
    "fedex_saves", "fedex_saves_pct", "weight_oz", "length", "width", "height",
]
PG = bool(config.DATABASE_URL)


class _Cursor:
    """Small wrapper so the same SQL (with ? placeholders) runs on SQLite and PostgreSQL."""

    def __init__(self, con):
        self.con = con

    def execute(self, sql, params=()):
        if PG:
            cur = self.con.cursor()
            cur.execute(sql.replace("?", "%s"), params)
            return cur
        return self.con.execute(sql, params)

    def fetchall(self, sql, params=()):
        cur = self.execute(sql, params)
        if PG:
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        return [dict(r) for r in cur.fetchall()]

    def fetchone(self, sql, params=()):
        rows = self.fetchall(sql, params)
        return rows[0] if rows else None


@contextmanager
def connect():
    if PG:
        import psycopg
        con = psycopg.connect(config.DATABASE_URL)
    else:
        con = sqlite3.connect(config.DB_PATH)
        con.row_factory = sqlite3.Row
    try:
        yield _Cursor(con)
        con.commit()
    finally:
        con.close()


def init():
    serial = "SERIAL PRIMARY KEY" if PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    statements = [
        f"CREATE TABLE IF NOT EXISTS snapshot (id {serial}, created_at TEXT NOT NULL, payload TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS manual_assign (order_id TEXT NOT NULL, sku TEXT NOT NULL, "
        "warehouse TEXT NOT NULL, PRIMARY KEY (order_id, sku))",
        "CREATE TABLE IF NOT EXISTS rate_cache (carrier TEXT NOT NULL, pkg_key TEXT NOT NULL, "
        "rates TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY (carrier, pkg_key))",
        f"CREATE TABLE IF NOT EXISTS archive (archive_key TEXT PRIMARY KEY, archived_at TEXT NOT NULL, "
        f"{', '.join(c + ' TEXT' for c in ARCHIVE_COLUMNS)})",
    ]
    with connect() as db:
        for s in statements:
            db.execute(s)


def _upsert(table, cols, keys):
    """INSERT ... that replaces an existing row with the same key."""
    placeholders = ", ".join("?" * len(cols))
    if PG:
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in keys)
        return (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {updates}")
    return f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"


# --- snapshot ---------------------------------------------------------------
def save_snapshot(payload):
    with connect() as db:
        db.execute("INSERT INTO snapshot (created_at, payload) VALUES (?, ?)",
                   (datetime.now().strftime("%Y-%m-%d %H:%M"), json.dumps(payload)))
        # keep the last 20 refreshes only
        db.execute("DELETE FROM snapshot WHERE id NOT IN "
                   "(SELECT id FROM (SELECT id FROM snapshot ORDER BY id DESC LIMIT 20) AS keep)")


def latest_snapshot():
    with connect() as db:
        row = db.fetchone("SELECT created_at, payload FROM snapshot ORDER BY id DESC LIMIT 1")
    if not row:
        return None, None
    return row["created_at"], json.loads(row["payload"])


# --- manual warehouse assignment ----------------------------------------------
def manual_assignments():
    with connect() as db:
        return {(r["order_id"], r["sku"]): r["warehouse"] for r in db.fetchall("SELECT * FROM manual_assign")}


def set_manual(order_id, sku, warehouse):
    with connect() as db:
        if warehouse:
            db.execute(_upsert("manual_assign", ["order_id", "sku", "warehouse"], ["order_id", "sku"]),
                       (order_id, sku, warehouse))
        else:
            db.execute("DELETE FROM manual_assign WHERE order_id = ? AND sku = ?", (order_id, sku))


# --- rate cache -----------------------------------------------------------------
def cached_rates(carrier, keys):
    keys = list(keys)
    if not keys:
        return {}
    cutoff = (datetime.now() - timedelta(hours=config.RATE_CACHE_HOURS)).isoformat()
    with connect() as db:
        rows = db.fetchall("SELECT pkg_key, rates FROM rate_cache WHERE carrier = ? AND fetched_at > ?",
                           (carrier, cutoff))
    wanted = set(keys)
    return {r["pkg_key"]: json.loads(r["rates"]) for r in rows if r["pkg_key"] in wanted}


def store_rates(carrier, rates):
    now = datetime.now().isoformat()
    sql = _upsert("rate_cache", ["carrier", "pkg_key", "rates", "fetched_at"], ["carrier", "pkg_key"])
    with connect() as db:
        for k, v in rates.items():
            db.execute(sql, (carrier, k, json.dumps(v), now))


# --- comparison archive ---------------------------------------------------------
def archive_rows(rows):
    """Adds comparison rows not archived yet (one per Order ID + SKU). Returns how many were added."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    cols = ["archive_key", "archived_at"] + ARCHIVE_COLUMNS
    placeholders = ", ".join("?" * len(cols))
    if PG:
        sql = f"INSERT INTO archive ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT (archive_key) DO NOTHING"
    else:
        sql = f"INSERT OR IGNORE INTO archive ({', '.join(cols)}) VALUES ({placeholders})"
    added = 0
    with connect() as db:
        for r in rows:
            values = [f"{r['order_id']}|{r['sku']}", stamp] + \
                     ["" if r.get(c) is None else str(r.get(c)) for c in ARCHIVE_COLUMNS]
            added += db.execute(sql, values).rowcount
    return added


def archive_page(search="", limit=500):
    with connect() as db:
        if search:
            like = f"%{search}%"
            rows = db.fetchall("SELECT * FROM archive WHERE order_id LIKE ? OR order_number LIKE ? OR sku LIKE ? "
                               "ORDER BY archived_at DESC LIMIT ?", (like, like, like, limit))
        else:
            rows = db.fetchall("SELECT * FROM archive ORDER BY archived_at DESC LIMIT ?", (limit,))
        total = db.fetchone("SELECT COUNT(*) AS n FROM archive")["n"]
    return rows, total


def archive_all():
    with connect() as db:
        return db.fetchall("SELECT * FROM archive ORDER BY archived_at DESC")
