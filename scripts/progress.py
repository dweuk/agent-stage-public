"""Show the progress of the search agent, live, in the terminal.

`scripts/search.sh` runs `claude -p --output-format stream-json --verbose`: Claude Code then writes one JSON event
per line (tool called, tool result, text of the agent, final result). This script reads these events on
stdin and prints one short line for each step.

Offer texts come from websites: they are untrusted. Nothing from a tool result is printed except numbers,
short error messages and short fields, always cleaned of control characters (no terminal escape codes).

Usage (done by search.sh): claude -p ... --output-format stream-json --verbose | .venv/bin/python scripts/progress.py
"""

import json
import os
import re
import select
import sys
import time

HEARTBEAT = 30          # seconds without news before a "still working" line
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

SERVER_NAMES = {
    "memory": "memory",
    "la-bonne-alternance": "La bonne alternance",
    "ats": "ATS career pages",
    "claude_ai_Indeed": "Indeed",
}

START = time.monotonic()
pending = {}            # tool_use_id → short label of the call, while it runs
indeed = {"searches": 0, "search_refused": 0, "details": 0, "details_refused": 0}


def clean(text, limit: int = 150) -> str:
    """One line, no control characters, at most `limit` characters."""
    text = CONTROL_CHARS.sub(" ", str(text)).strip()
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def say(message: str) -> None:
    elapsed = int(time.monotonic() - START)
    print(f"[{elapsed // 60:02d}:{elapsed % 60:02d}] {message}", flush=True)


def label(name: str, tool_input: dict) -> str:
    """Short, readable name of a tool call."""
    if name.startswith("mcp__"):
        _, server, tool = (name.split("__", 2) + ["", ""])[:3]
        server = SERVER_NAMES.get(server, server)
        if tool == "search_jobs":
            return f"Indeed search '{clean(tool_input.get('search'), 50)}' in {clean(tool_input.get('location'), 30)}"
        if tool == "get_job_details":
            return "Indeed offer details"
        if tool == "get_offer_details":
            return f"{server}: details of {len(tool_input.get('ids') or [])} offers"
        if tool == "filter_already_seen":
            return f"memory: check {len(tool_input.get('ids') or [])} ids already seen"
        if tool == "save_evaluations":
            return "memory: save the results"
        return f"{server}: {tool}"
    if name == "Skill":
        return f"load skill {clean(tool_input.get('skill'), 40)}"
    if name == "Read":
        return f"read {clean(os.path.basename(tool_input.get('file_path', '')), 60)}"
    if name in ("Write", "Edit"):
        return f"write {clean(tool_input.get('file_path', ''), 80)}"
    return clean(name, 60)


def result_text(content) -> str:
    """The text of a tool result (a string, or a list of text blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block.get("text", "") for block in content if isinstance(block, dict))
    return ""


def summary(call: str, text: str) -> str:
    """A few numbers about a successful result, when we can find them."""
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict) and "offer_count" in data:
        errors = len(data.get("errors") or [])
        removed = len(data.get("removed_by_code") or [])
        extra = f", {removed} removed by the code" if removed else ""
        extra += f", !!! {errors} errors" if errors else ""
        return f"{data['offer_count']} offers{extra}"
    if isinstance(data, list):
        return f"{len(data)} items"
    if call.startswith("Indeed search"):
        return f"{text.count('Job Id')} offers"
    return "done"


def on_event(event: dict) -> None:
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        say(f"Agent started (model: {clean(event.get('model'), 40)})")
        for server in event.get("mcp_servers") or []:
            status = server.get("status")
            name = clean(server.get("name"), 40)
            if name.startswith("claude.ai ") and "Indeed" not in name:
                continue   # the other connectors are denied anyway
            mark = "v" if status == "connected" else "❌"
            say(f"  {mark} {name}: {clean(status, 40)}")
    elif kind == "assistant":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "text" and block.get("text", "").strip():
                say(f"--- {clean(block['text'], 200)}")
            elif block.get("type") == "tool_use":
                call = label(block.get("name", ""), block.get("input") or {})
                pending[block.get("id")] = call
                say(f"→ {call}…")
    elif kind == "user":
        content = event.get("message", {}).get("content", [])
        for block in content if isinstance(content, list) else []:
            if block.get("type") != "tool_result":
                continue
            call = pending.pop(block.get("tool_use_id"), "tool")
            text = result_text(block.get("content"))
            refused = "rate limit" in text.lower() or "-32429" in text
            if call.startswith("Indeed search"):
                indeed["searches"] += 1
                indeed["search_refused"] += refused
            elif call.startswith("Indeed offer"):
                indeed["details"] += 1
                indeed["details_refused"] += refused
            if refused:
                say(f"⏳ {call}: refused (Indeed call limit), the agent will try again later")
            elif block.get("is_error"):
                say(f"❌ {call}: {clean(text)}")
            else:
                say(f"✅ {call}: {summary(call, text)}")
    elif kind == "result":
        seconds = int((event.get("duration_ms") or 0) / 1000)
        say(f"Finished in {seconds // 60} min {seconds % 60} s ({event.get('num_turns', '?')} turns)")
        if indeed["searches"] or indeed["details"]:
            say(f"Indeed: {indeed['searches']} searches ({indeed['search_refused']} refused), "
                f"{indeed['details']} offer details ({indeed['details_refused']} refused)")
        status = "❌ The agent stopped with an error" if event.get("is_error") else "Last message of the agent"
        print(f"\n{status}:\n{CONTROL_CHARS.sub(' ', str(event.get('result', ''))).strip()}", flush=True)


def main() -> None:
    fd = sys.stdin.fileno()
    buffer = b""
    while True:
        ready, _, _ = select.select([fd], [], [], HEARTBEAT)
        if not ready:
            waiting = ", ".join(sorted(set(pending.values()))) or "the agent is thinking"
            say(f"… still working ({clean(waiting, 120)})")
            continue
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        buffer += chunk
        *lines, buffer = buffer.split(b"\n")
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue   # not an event (should not happen): ignore it
            if not isinstance(event, dict):
                continue
            # A crash here would close the pipe and kill `claude` (SIGPIPE) in the middle of the search.
            try:
                on_event(event)
            except Exception as error:
                say(f"(progress display: event not understood, {type(error).__name__})")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
