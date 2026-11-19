"""Tests of scripts/agent_docker.sh: what each agent can see. Dry run only: no Docker, no Claude."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "agent_docker.sh"
JOBS = ["search", "search-test", "apply", "track"]


def run(job: str, memory_db: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "AGENT_DOCKER_DRY_RUN": "1", "OUT_DIR": "applications/zz-dry-run/parts/01-a"}
    env.pop("MEMORY_DB", None)
    if memory_db:
        env["MEMORY_DB"] = memory_db
    return subprocess.run(["bash", SCRIPT, job, "-p", "hello"], env=env, capture_output=True, text=True)


def mounts(job: str) -> list[str]:
    """The container paths of the mounts of a job."""
    args = run(job).stdout.splitlines()
    return [args[i + 1].split(":")[1] for i, arg in enumerate(args) if arg == "-v"]


@pytest.fixture(autouse=True)
def remove_dry_run_folder():
    yield
    folder = SCRIPT.parents[1] / "applications" / "zz-dry-run"
    if folder.is_dir():
        subprocess.run(["rm", "-rf", folder], check=True)


@pytest.mark.parametrize("job", JOBS)
def test_no_job_sees_secrets_or_the_whole_project(job):
    paths = mounts(job)
    assert "/app" not in paths
    for path in paths:
        assert not path.startswith(("/app/.env", "/app/.git", "/app/.venv", "/app/.claude/settings.local"))
        assert path != "/app/tests/expected_results.md"


@pytest.mark.parametrize("job", ["search", "search-test", "track"])
def test_only_apply_sees_my_profile_and_drafts(job):
    assert not any(path.startswith(("/app/profile", "/app/applications")) for path in mounts(job))


def test_apply_sees_only_its_own_folder_and_2_profile_files():
    paths = mounts("apply")
    assert "/app/applications/zz-dry-run/parts/01-a" in paths and "/app/applications" not in paths
    assert {path for path in paths if path.startswith("/app/profile")} == \
        {"/app/profile/cv.md", "/app/profile/email-base.md"}


@pytest.mark.parametrize("job, skill", [("search", "search-offers"), ("apply", "prepare-application"),
                                        ("track", "tracking")])
def test_each_job_sees_only_its_skill(job, skill):
    skills = [path for path in mounts(job) if path.startswith("/app/.claude/skills")]
    assert skills == [f"/app/.claude/skills/{skill}"]


@pytest.mark.parametrize("job, seen", [("search", True), ("apply", True), ("search-test", False), ("track", False)])
def test_search_settings_only_for_the_jobs_that_need_them(job, seen):
    assert ("/app/config/search.json" in mounts(job)) == seen
    assert "/app/config" not in mounts(job)


def test_fake_offers_only_in_test_mode():
    assert "/app/tests/fake_offers.json" in mounts("search-test")
    assert not any(path.startswith("/app/tests") for path in mounts("search"))


@pytest.mark.parametrize("job", JOBS)
def test_container_is_hardened(job):
    args = run(job).stdout.splitlines()
    for flag in ("--read-only", "--init", "--rm"):
        assert flag in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert args[args.index("--security-opt") + 1] == "no-new-privileges"


@pytest.mark.parametrize("job", JOBS)
def test_no_env_file_given_to_the_container(job):
    assert "--env-file" not in run(job).stdout


def test_memory_db_folder_is_mounted(tmp_path):
    result = run("track", str(tmp_path / "own" / "offers.db"))
    assert result.returncode == 0
    assert "MEMORY_DB=/memory/offers.db" in result.stdout.splitlines()


# /private/tmp is the real /tmp of macOS only: on Linux (GitHub Actions), /private does not exist and cannot be created.
MACOS_ONLY = pytest.mark.skipif(sys.platform != "darwin", reason="/private/tmp exists only on macOS")


@pytest.mark.parametrize("path", ["/tmp/check.db", pytest.param("/private/tmp/check.db", marks=MACOS_ONLY),
                                  str(SCRIPT.parents[1] / "x.db"), str(SCRIPT.parents[2] / "x.db")])
def test_memory_db_refuses_a_folder_with_other_files(path):
    result = run("track", path)
    assert result.returncode == 1 and "own folder" in result.stderr


def test_unknown_job_is_refused():
    assert run("shell").returncode == 1
