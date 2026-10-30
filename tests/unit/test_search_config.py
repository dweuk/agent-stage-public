"""Tests of mcp/search_config.py and of what each server does with the settings. No network."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "config" / "search.example.json"
sys.path.insert(0, str(ROOT / "mcp"))

import search_config  # noqa: E402


def load_server(name: str, config: Path, monkeypatch, tmp_path):
    """A fresh copy of a server, which reads `config` at import time."""
    monkeypatch.setattr(search_config, "CONFIG_PATH", config)
    monkeypatch.setenv("RETURNED_URLS_LOG", str(tmp_path / "urls.jsonl"))
    spec = importlib.util.spec_from_file_location(f"{name}_server_test", ROOT / "mcp" / name / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_file_gives_an_empty_section(monkeypatch, tmp_path):
    monkeypatch.setattr(search_config, "CONFIG_PATH", tmp_path / "missing.json")
    assert search_config.section("ats") == {}


def test_example_has_a_section_for_each_server():
    settings = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert {"la_bonne_alternance", "ats", "memory"} <= settings.keys()


@pytest.mark.parametrize("name", ["ats", "la_bonne_alternance"])
def test_search_without_settings_says_what_to_do(name, monkeypatch, tmp_path):
    server = load_server(name, tmp_path / "missing.json", monkeypatch, tmp_path)
    with pytest.raises(server.ToolError, match="config/search.example.json"):
        asyncio.run(server.search_offers())


def test_ats_reads_the_example(monkeypatch, tmp_path):
    server = load_server("ats", EXAMPLE, monkeypatch, tmp_path)
    assert server.COMPANY_OF[("lever", "exampleboard")] == "Example company"
    assert server.JOB_TITLE.search("Stage COMPTABLE") and not server.JOB_TITLE.search("Stage cuisine")
    assert server.in_zone("", "69003") and not server.in_zone("", "13001")
    assert server.in_zone("Nantes", "") and not server.in_zone("Marseille", "")


@pytest.mark.parametrize("board, valid", [("exampleboard", True), ("example-board", True), ("example_board", True),
                                          ("../x", False), ("x?y=1", False)])
def test_ats_id_accepts_a_board_with_a_hyphen_and_nothing_dangerous(board, valid, monkeypatch, tmp_path):
    server = load_server("ats", EXAMPLE, monkeypatch, tmp_path)
    assert bool(server.ID_PATTERN.fullmatch(f"ats:lever:{board}:abc-1")) == valid


def test_la_bonne_alternance_ids_can_be_read_again_by_its_own_server(monkeypatch, tmp_path):
    """No offer gets the id of another source: apply.sh asks the details to the server named in the id."""
    server = load_server("la_bonne_alternance", EXAMPLE, monkeypatch, tmp_path)
    job = {"identifier": {"id": "0123456789abcdef01234567", "partner_label": "France Travail", "partner_job_id": "1A"}}
    assert server.LBA_ID_PATTERN.fullmatch(server.common_id(job))


def test_memory_areas_come_from_the_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_DB", str(tmp_path / "offers.db"))
    server = load_server("memory", EXAMPLE, monkeypatch, tmp_path)
    assert server.area_of("69 - Lyon 3e") == server.area_of("Bourg (01)") == server.area_of("Lyon, France") == "lyon-area"
    assert server.area_of("Nantes") == server.area_of("44000 Nantes") == "44"
    assert server.area_of("Marseille") == ""


def test_memory_without_settings_uses_only_the_department(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_DB", str(tmp_path / "offers.db"))
    server = load_server("memory", tmp_path / "missing.json", monkeypatch, tmp_path)
    assert server.area_of("Lyon 3e (69)") == "69" and server.area_of("Lyon") == ""
