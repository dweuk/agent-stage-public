"""Tests of scripts/check_links.py: the traps of a report. No network."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_links.py"
KNOWN = "https://jobs.lever.co/acme/1"


def check(tmp_path: Path, text: str) -> subprocess.CompletedProcess:
    log = tmp_path / "urls.jsonl"
    log.write_text(f'{{"id": "ats:lever:acme:1", "url": "{KNOWN}", "date": "2026-10-30"}}\n')
    report = tmp_path / "report.md"
    report.write_text(text)
    return subprocess.run([sys.executable, SCRIPT, report], capture_output=True, text=True,
                          env={"RETURNED_URLS_LOG": str(log), "PYTHONDONTWRITEBYTECODE": "1"})


def test_a_link_returned_by_a_server_is_ok(tmp_path):
    result = check(tmp_path, f"[offre]({KNOWN})")
    assert result.returncode == 0 and "OK" in result.stdout


@pytest.mark.parametrize("link", ["https://attacker.example/x", "HTTPS://attacker.example/x",
                                  "hTtP://attacker.example/x", "Https://jobs.lever.co.attacker.example/x"])
def test_a_link_that_no_server_returned_is_danger_whatever_its_case(tmp_path, link):
    result = check(tmp_path, f"[postuler]({link})")
    assert result.returncode == 1 and "DANGER" in result.stdout


def test_no_terminal_escape_code_is_printed(tmp_path):
    result = check(tmp_path, "![x](https://attacker.example/\x1b[2Jx)\nhttps://attacker.example/\x1b]0;x\x07y\n")
    assert result.returncode == 1 and "\x1b" not in result.stdout and "\x07" not in result.stdout


def test_a_missing_report_is_not_a_danger(tmp_path):
    result = subprocess.run([sys.executable, SCRIPT, tmp_path / "missing.md"], capture_output=True, text=True)
    assert result.returncode == 2
