"""SQLite como índice reconstruible. La verdad vive en disco + sidecars XMP."""
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders(
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    photo_count INTEGER NOT NULL DEFAULT 0,
    last_scan REAL
);
CREATE TABLE IF NOT EXISTS photos(
    id INTEGER PRIMARY KEY,
    folder_id INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    stem TEXT NOT NULL,
    ext TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    mtime REAL NOT NULL,
    taken_at TEXT,
    rating INTEGER,
    UNIQUE(folder_id, stem, ext)
);
CREATE INDEX IF NOT EXISTS idx_photos_folder ON photos(folder_id);
"""


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    con = sqlite3.connect(config.DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    return con
