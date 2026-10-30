"""Log of the offer URLs returned by the MCP servers, shared by the servers that read offers.

Each server writes the URL of every offer it formats in `data/returned_urls.jsonl` (one JSON line per URL).
`scripts/check_links.py` then checks that each link of a report is in this log: a link that no server
returned was invented by the agent or copied from the text of an offer (prompt injection).
The agent cannot read or change this file (`Read(./data/**)` and `Edit(./data/**)` are denied).
"""

import datetime
import functools
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # the agent-stage-public/ folder
# RETURNED_URLS_LOG lets the tests use another file.
LOG_PATH = Path(os.environ.get("RETURNED_URLS_LOG", ROOT / "data" / "returned_urls.jsonl"))

_written: set[str] = set()  # URLs already written by this process: the log stays small


def remember_url(offer_id: str, url: str) -> None:
    """Add one URL to the log (once per process). Values that are not web links are ignored."""
    if not url.startswith("https://") or url in _written:
        return
    _written.add(url)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = {"id": offer_id, "url": url, "date": datetime.date.today().isoformat()}
    with LOG_PATH.open("a") as log:
        log.write(json.dumps(line, ensure_ascii=False) + "\n")


def logs_url(format_function):
    """Decorator for the `common_format` of a server: every formatted offer has its URL logged."""
    @functools.wraps(format_function)
    def wrapper(*args, **kwargs) -> dict:
        offer = format_function(*args, **kwargs)
        remember_url(offer["id"], offer["url"])
        return offer
    return wrapper


def load_urls(path: Path = LOG_PATH) -> set[str] | None:
    """All the URLs of the log, or None if the log does not exist yet."""
    if not path.is_file():
        return None
    urls = set()
    for line in path.read_text().splitlines():
        try:
            urls.add(json.loads(line)["url"])
        except (json.JSONDecodeError, KeyError, TypeError):
            continue  # a broken line: skip it, the other lines still count
    return urls
