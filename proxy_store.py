"""
proxy_store.py - persistent proxy database.

Every proxy ever discovered is stored in SQLite with timestamps and its last
check result. This lets the pool grow day after day instead of being rebuilt
from scratch: proxies that were dead yesterday are re-checked and can return.

Used by fetch_proxies.py.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS proxies (
    key        TEXT PRIMARY KEY,
    scheme     TEXT NOT NULL,
    host       TEXT NOT NULL,
    port       INTEGER NOT NULL,
    first_seen REAL NOT NULL,
    last_seen  REAL NOT NULL,
    last_check REAL,
    alive      INTEGER,          -- 1 = worked, 0 = failed, NULL = never checked
    latency_ms REAL,
    successes  INTEGER NOT NULL DEFAULT 0,
    failures   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    ok_count   INTEGER NOT NULL DEFAULT 0,   -- times it passed a check
    check_count INTEGER NOT NULL DEFAULT 0   -- times it was checked
);
CREATE INDEX IF NOT EXISTS idx_alive ON proxies(alive, latency_ms);
CREATE INDEX IF NOT EXISTS idx_host ON proxies(host);
"""


class ProxyStore:
    def __init__(self, path: str | Path = "proxies.db"):
        self.path = Path(path)
        self.db = sqlite3.connect(str(self.path))
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(proxies)")}
        for name, ddl in (
            ("ok_count", "INTEGER NOT NULL DEFAULT 0"),
            ("check_count", "INTEGER NOT NULL DEFAULT 0"),
            ("best_ms", "REAL"),
        ):
            if name not in cols:
                self.db.execute(f"ALTER TABLE proxies ADD COLUMN {name} {ddl}")
        # index that depends on the migrated columns
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_quality ON proxies(alive, ok_count, latency_ms)"
        )

    # ---- writing -------------------------------------------------------
    def add_many(self, proxies) -> int:
        """Insert newly seen proxies. Returns how many were new."""
        now = time.time()
        new = 0
        for p in proxies:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO proxies"
                "(key,scheme,host,port,first_seen,last_seen) VALUES(?,?,?,?,?,?)",
                (p.key, p.scheme, p.host, p.port, now, now),
            )
            if cur.rowcount:
                new += 1
            else:
                self.db.execute(
                    "UPDATE proxies SET last_seen=? WHERE key=?", (now, p.key)
                )
        self.db.commit()
        return new

    def update_results(self, proxies) -> None:
        """Record the latest health-check outcome for each proxy."""
        now = time.time()
        rows = []
        for p in proxies:
            if p.checked_at == 0:
                continue          # not checked in this run
            ok = 1 if p.alive else 0
            rows.append((
                ok,
                p.latency_ms,
                p.successes,
                p.failures,
                (p.last_error or "")[:200],
                now,
                ok,               # ok_count increment
                p.key,
            ))
        self.db.executemany(
            "UPDATE proxies SET alive=?, latency_ms=?, successes=?, failures=?,"
            " last_error=?, last_check=?, check_count=check_count+1,"
            " ok_count=ok_count+?,"
            " best_ms=CASE WHEN ?=1 THEN MIN(COALESCE(best_ms, 1e9), COALESCE(?,1e9))"
            "               ELSE best_ms END"
            " WHERE key=?",
            [r[:7] + (r[0],) + (r[1],) + (r[7],) for r in rows],
        )
        self.db.commit()

    # ---- reading -------------------------------------------------------
    def alive_keys(self, max_latency_ms: float | None = None) -> list[str]:
        sql = "SELECT key FROM proxies WHERE alive=1"
        args: tuple = ()
        if max_latency_ms is not None:
            sql += " AND latency_ms IS NOT NULL AND latency_ms <= ?"
            args = (max_latency_ms,)
        sql += " ORDER BY latency_ms IS NULL, latency_ms"
        return [r[0] for r in self.db.execute(sql, args)]

    def stale(self, older_than_s: float, limit: int = 5000) -> list[tuple[str, str, str, int]]:
        """Proxies not checked recently, for re-checking without a fresh download."""
        cutoff = time.time() - older_than_s
        return list(self.db.execute(
            "SELECT key, scheme, host, port FROM proxies"
            " WHERE last_check IS NULL OR last_check < ?"
            " ORDER BY last_check IS NULL DESC, last_check ASC LIMIT ?",
            (cutoff, limit),
        ))

    def quality_keys(self, max_latency_ms: float = 3000, min_ok: int = 2) -> list[str]:
        """High-quality pool: alive, proven across checks, and fast at its best."""
        return [r[0] for r in self.db.execute(
            "SELECT key FROM proxies"
            " WHERE alive=1 AND ok_count >= ?"
            " AND COALESCE(best_ms, latency_ms, 1e9) <= ?"
            " ORDER BY COALESCE(best_ms, latency_ms, 1e9)",
            (min_ok, max_latency_ms),
        )]

    def all_keys(self) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT key FROM proxies")}

    def alive_entries(self, limit: int = 0) -> list[tuple[str, str, str, int]]:
        """Everything currently believed alive - the candidates worth hourly re-checking."""
        sql = "SELECT key, scheme, host, port FROM proxies WHERE alive=1"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return list(self.db.execute(sql))

    def dead_entries(self, limit: int = 0) -> list[tuple[str, str, str, int]]:
        """Proxies currently marked dead, for a second-chance re-check."""
        sql = "SELECT key, scheme, host, port FROM proxies WHERE alive=0"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return list(self.db.execute(sql))

    def all_proxies(self, limit: int | None = None) -> list[tuple[str, str, str, int]]:
        sql = "SELECT key, scheme, host, port FROM proxies"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return list(self.db.execute(sql))

    def stats(self) -> dict:
        cur = self.db.execute(
            "SELECT COUNT(*), SUM(alive=1), SUM(alive=0),"
            " COUNT(DISTINCT host),"
            " SUM(last_check > ?) FROM proxies",
            (time.time() - 86400,),
        )
        total, alive, dead, hosts, checked_24h = cur.fetchone()
        quality = self.db.execute(
            "SELECT COUNT(*) FROM proxies WHERE alive=1 AND ok_count >= 2"
            " AND COALESCE(best_ms, latency_ms, 1e9) <= 3000"
        ).fetchone()[0]
        return {
            "total": total or 0,
            "alive": alive or 0,
            "dead": dead or 0,
            "quality": quality or 0,
            "unique_ips": hosts or 0,
            "checked_24h": checked_24h or 0,
        }

    def close(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass
