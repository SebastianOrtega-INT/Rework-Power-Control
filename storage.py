import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Operator:
    wwid: str
    name: str


class StationStore:
    def __init__(self, path):
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        with self.connection:
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS operators (
                    wwid TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY,
                    station INTEGER NOT NULL,
                    wwid TEXT NOT NULL REFERENCES operators(wwid),
                    operator_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    planned_minutes INTEGER NOT NULL,
                    ended_at TEXT,
                    end_reason TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_open_session_per_station
                    ON sessions(station) WHERE ended_at IS NULL;
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY,
                    station INTEGER NOT NULL,
                    issue TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    @staticmethod
    def timestamp():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def lookup_operator(self, wwid):
        row = self.connection.execute(
            "SELECT wwid, name FROM operators WHERE wwid = ? AND active = 1",
            (wwid.strip(),),
        ).fetchone()
        return Operator(row["wwid"], row["name"]) if row else None

    def start_session(self, station, wwid, minutes):
        if station not in (1, 2, 3, 4) or minutes not in (15, 30, 45, 60):
            raise ValueError("Estacion o duracion no valida.")
        with self.connection:
            operator = self.lookup_operator(wwid)
            if operator is None:
                raise ValueError("WWID no registrado o usuario inactivo.")
            cursor = self.connection.execute(
                """INSERT INTO sessions
                   (station, wwid, operator_name, started_at, planned_minutes)
                   VALUES (?, ?, ?, ?, ?)""",
                (station, operator.wwid, operator.name, self.timestamp(), minutes),
            )
        return cursor.lastrowid, operator

    def finish_session(self, session_id, reason):
        with self.connection:
            self.connection.execute(
                "UPDATE sessions SET ended_at = ?, end_reason = ? "
                "WHERE id = ? AND ended_at IS NULL",
                (self.timestamp(), reason, session_id),
            )

    def recover_sessions(self):
        with self.connection:
            self.connection.execute(
                "UPDATE sessions SET ended_at = ?, end_reason = 'interrupted' "
                "WHERE ended_at IS NULL",
                (self.timestamp(),),
            )

    def recent_sessions(self):
        return self.connection.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT 200"
        ).fetchall()

    def save_report(self, station, issue, notes):
        with self.connection:
            self.connection.execute(
                "INSERT INTO reports (station, issue, notes, created_at) VALUES (?, ?, ?, ?)",
                (station, issue, notes.strip(), self.timestamp()),
            )

    def load_demo_operators(self):
        with self.connection:
            self.connection.executemany(
                "INSERT OR IGNORE INTO operators (wwid, name) VALUES (?, ?)",
                [
                    ("100001", "Ana Garcia (DEMO)"),
                    ("100002", "Luis Perez (DEMO)"),
                    ("12351003", "José Sebastián González Ortega"),
                ],
            )

    def close(self):
        self.connection.close()


DEFAULT_DATABASE = Path(__file__).resolve().parent / "rework.db"