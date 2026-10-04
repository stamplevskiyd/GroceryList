"""Exercise deployment failure boundaries without a VPS, network or real Docker."""

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from tests.support import REPO_ROOT

COMMIT = "a" * 40
TAG = "v0.1.0"

FAKE_DOCKER = """
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as log:
    log.write(json.dumps(args) + "\\n")
failure = os.environ.get("FAIL", "")
if args[:2] == ["image", "inspect"]:
    print(json.dumps([{"Config": {"Labels": {
        "org.opencontainers.image.revision": "b" * 40 if failure == "revision" else "a" * 40,
        "org.opencontainers.image.version": "wrong" if failure == "version" else os.environ["TAG"],
    }}}]))
elif "config" in args:
    url = "http://example.test" if failure == "https" else "https://example.test"
    print(json.dumps({"services": {
        "caddy": {"image": "example/caddy:test", "environment": {"APP_PUBLIC_URL": url}},
        "backend": {"image": "example/backend:test"},
    }}))
elif "pull" in args and failure == "pull":
    sys.exit(1)
elif "run" in args and failure == "backup":
    sys.exit(1)
elif "up" in args and args[-1] != "postgres" and failure == "startup":
    sys.exit(1)
elif "prune" in args and failure == "prune":
    sys.exit(1)
"""


def executable(path: Path, body: str) -> None:
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(0o755)


def run(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # Trusted test executables, no shell parsing and no production commands.
    return subprocess.run(  # noqa: S603
        command, cwd=cwd, env=env, capture_output=True, text=True, timeout=20, check=False
    )


def setup_remote(tmp_path: Path, failure: str = "", tag: str = TAG) -> tuple[Path, dict[str, str]]:
    release = tmp_path / "releases" / "candidate"
    scripts = release / "scripts"
    scripts.mkdir(parents=True)
    for name in ("deploy_remote.sh", "release_lib.sh"):
        shutil.copyfile(REPO_ROOT / "scripts" / name, scripts / name)
    (tmp_path / ".env").write_text("APP_PUBLIC_URL=https://example.test\n")
    old = tmp_path / "releases" / "old"
    old.mkdir()
    (old / "deploy.env").write_text("IMAGE_TAG=v0.0.1\n")
    (tmp_path / "last-successful").symlink_to(old)
    (tmp_path / "current").symlink_to(old)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    executable(binaries / "docker", FAKE_DOCKER)
    executable(binaries / "flock", "import os, sys; sys.exit(os.environ.get('FAIL') == 'lock')")
    executable(binaries / "sleep", "")
    executable(
        binaries / "curl",
        'import json, os; print(json.dumps({"status": "ok", "version": '
        '"wrong" if os.environ.get("FAIL") == "health" else os.environ["TAG"]}))',
    )
    env = {
        **os.environ,
        "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
        "CALLS": str(tmp_path / "calls.jsonl"),
        "FAIL": failure,
        "TAG": tag,
    }
    return release, env


def deploy_remote(
    root: Path, release: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return run(
        [
            "/bin/bash",
            str(release / "scripts/deploy_remote.sh"),
            str(root),
            env["TAG"],
            COMMIT,
            str(release),
        ],
        root,
        env,
    )


def docker_calls(root: Path) -> list[list[str]]:
    path = root / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize("tag", [TAG, COMMIT[:12]])
def test_deploy_success_backs_up_before_migration_and_checks_version(
    tmp_path: Path, tag: str
) -> None:
    release, env = setup_remote(tmp_path, tag=tag)
    result = deploy_remote(tmp_path, release, env)
    assert result.returncode == 0, result.stderr
    calls = docker_calls(tmp_path)
    backup = next(i for i, args in enumerate(calls) if "run" in args)
    startup = next(i for i, args in enumerate(calls) if "up" in args and args[-1] != "postgres")
    assert backup < startup
    assert calls[backup][-1] == f"pre-deploy-{tag.replace('.', '_')}"
    assert "--no-build" in calls[startup]
    assert (tmp_path / "last-successful").resolve() == release
    assert (tmp_path / "current").resolve() == release
    assert (release / "deploy.env").read_text() == f"IMAGE_TAG={tag}\n"
    assert calls[-1] == ["image", "prune", "--force", "--filter", "until=24h"]


@pytest.mark.parametrize(
    "failure", ["lock", "https", "pull", "revision", "version", "backup", "startup", "health"]
)
def test_deploy_failure_preserves_last_successful_and_never_prunes(
    tmp_path: Path, failure: str
) -> None:
    release, env = setup_remote(tmp_path, failure)
    result = deploy_remote(tmp_path, release, env)
    assert result.returncode != 0
    calls = docker_calls(tmp_path)
    assert not any("prune" in args for args in calls)
    assert (tmp_path / "last-successful").resolve().name == "old"
    if failure not in {"startup", "health"}:
        assert not any("up" in args and args[-1] != "postgres" for args in calls)
        assert (tmp_path / "current").resolve().name == "old"
    if failure not in {"lock"}:
        assert "Previous successful tag: v0.0.1" in result.stderr


@pytest.mark.parametrize("tag", ["latest", "main", "../v1", "v1;id", "$(id)", "", "a" * 13])
def test_invalid_deploy_tag_never_reaches_ssh(tmp_path: Path, tag: str) -> None:
    env = {**os.environ, "VPS_HOST": "example.test", "VPS_USER": "deploy"}
    result = run(["/bin/bash", str(REPO_ROOT / "scripts/deploy.sh"), tag], tmp_path, env)
    assert result.returncode != 0
    assert "VPS_KNOWN_HOSTS" not in result.stderr


def test_cleanup_failure_does_not_fail_a_healthy_deployment(tmp_path: Path) -> None:
    release, env = setup_remote(tmp_path, "prune")
    result = deploy_remote(tmp_path, release, env)
    assert result.returncode == 0, result.stderr
    assert "image cleanup failed" in result.stderr
    assert (tmp_path / "last-successful").resolve() == release


def test_upload_uses_selected_commit_and_pinned_host_key(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("deploy.sh", "release_lib.sh", "deploy_remote.sh", "pg_backup.sh"):
        shutil.copyfile(REPO_ROOT / "scripts" / name, scripts / name)
    (tmp_path / "docker-compose.yml").write_text("committed compose\n")
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1"}
    for args in (
        ["init", "--quiet"],
        ["add", "."],
        [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.test",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "release",
        ],
        ["tag", TAG],
    ):
        result = run(["git", *args], tmp_path, env)
        assert result.returncode == 0, result.stderr
    (tmp_path / "docker-compose.yml").write_text("uncommitted compose\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    executable(
        binaries / "ssh",
        "import json, os, sys\nfrom pathlib import Path\n"
        'with open(os.environ["CALLS"], "a") as log: log.write(json.dumps(sys.argv[1:]) + "\\n")\n'
        'if "tar -xf" in sys.argv[-1]:\n'
        '    Path(os.environ["ARCHIVE"]).write_bytes(sys.stdin.buffer.read())\n',
    )
    env.update(
        PATH=f"{binaries}{os.pathsep}{env['PATH']}",
        VPS_HOST="example.test",
        VPS_USER="deploy",
        VPS_KNOWN_HOSTS="example.test ssh-ed25519 test-only-key",
        VPS_SSH_KEY="test-only-private-key",
        CALLS=str(tmp_path / "calls.jsonl"),
        ARCHIVE=str(tmp_path / "uploaded.tar"),
    )
    env.pop("VPS_SSH_KEY_FILE", None)
    result = run(["/bin/bash", str(scripts / "deploy.sh"), TAG], tmp_path, env)
    assert result.returncode == 0, result.stderr
    calls = docker_calls(tmp_path)
    assert len(calls) == 2
    assert all("StrictHostKeyChecking=yes" in args for args in calls)
    assert all("GlobalKnownHostsFile=/dev/null" in args for args in calls)
    with tarfile.open(fileobj=io.BytesIO((tmp_path / "uploaded.tar").read_bytes())) as archive:
        member = archive.extractfile("docker-compose.yml")
        assert member is not None
        assert member.read() == b"committed compose\n"
