import sqlite3
from pathlib import Path


class Checkpoint:
    def __init__(self, path: str | Path):
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS routes (osm_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL)")
        self.connection.commit()

    def get(self, osm_id: str) -> str | None:
        row = self.connection.execute("SELECT payload FROM routes WHERE osm_id = ? AND status = 'done'", (osm_id,)).fetchone()
        return row[0] if row else None

    def save(self, osm_id: str, payload: str) -> None:
        self.connection.execute("INSERT OR REPLACE INTO routes VALUES (?, 'done', ?)", (osm_id, payload))
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
