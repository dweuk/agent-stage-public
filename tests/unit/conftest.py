"""Shared setup of the unit tests: `.venv/bin/python -m pytest tests/unit`.

The tests never touch the real memory: MEMORY_DB points to a file of a temporary folder BEFORE the scripts are
imported (they read it at import time). No test calls the network, and none reads profile/.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

os.environ["MEMORY_DB"] = str(Path(tempfile.mkdtemp(prefix="agent-stage-tests-")) / "missing.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


@pytest.fixture
def memory_db(tmp_path):
    """Builds a memory database with the 2 tables the scripts read: make(offers=[(id, url)], tracking=[...])."""
    def make(offers=(), tracking=()):
        path = tmp_path / "offers.db"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE offers (id TEXT PRIMARY KEY, title TEXT, company TEXT, url TEXT, status TEXT)")
        db.execute("CREATE TABLE tracking (num INTEGER PRIMARY KEY, type TEXT, company TEXT, offer_id TEXT)")
        db.executemany("INSERT INTO offers (id, url, status) VALUES (?, ?, 'kept')", offers)
        db.executemany("INSERT INTO tracking (type, company, offer_id) VALUES (?, ?, ?)", tracking)
        db.commit()
        db.close()
        return path
    return make
