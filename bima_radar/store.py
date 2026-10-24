"""The Cover Map store. SQLite for the prototype; PostgreSQL in the full build."""

from __future__ import annotations

import json
import sqlite3

from bima_radar.models import Cover, LifeEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS covers (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS packs  (event_id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta   (key TEXT PRIMARY KEY, body TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(SCHEMA)

    def _put(self, table: str, key_col: str, key: str, body: dict):
        self.conn.execute(f"INSERT OR REPLACE INTO {table} ({key_col}, body) VALUES (?, ?)", (key, json.dumps(body, ensure_ascii=False)))
        self.conn.commit()

    def _get(self, table: str, key_col: str, key: str) -> dict | None:
        row = self.conn.execute(f"SELECT body FROM {table} WHERE {key_col} = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def replace_covers(self, covers: list[Cover]):
        self.conn.execute("DELETE FROM covers")
        for c in covers:
            self.conn.execute("INSERT INTO covers (id, body) VALUES (?, ?)", (c.id, json.dumps(c.to_dict(), ensure_ascii=False)))
        self.conn.commit()

    def add_cover(self, cover: Cover):
        self._put("covers", "id", cover.id, cover.to_dict())

    def covers(self) -> list[Cover]:
        return [Cover.from_dict(json.loads(b)) for (b,) in self.conn.execute("SELECT body FROM covers ORDER BY rowid")]

    def save_event(self, event: LifeEvent):
        self._put("events", "id", event.id, event.to_dict())

    def event(self, event_id: str) -> LifeEvent | None:
        d = self._get("events", "id", event_id)
        return LifeEvent.from_dict(d) if d else None

    def events(self) -> list[LifeEvent]:
        return [LifeEvent.from_dict(json.loads(b)) for (b,) in self.conn.execute("SELECT body FROM events ORDER BY rowid")]

    def save_pack(self, event_id: str, pack: dict):
        self._put("packs", "event_id", event_id, pack)

    def pack(self, event_id: str) -> dict | None:
        return self._get("packs", "event_id", event_id)

    def set_meta(self, key: str, value: dict):
        self._put("meta", "key", key, value)

    def meta(self, key: str) -> dict | None:
        return self._get("meta", "key", key)
