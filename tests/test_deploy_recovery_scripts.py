from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECOVERY_SCRIPT = ROOT / "deploy" / "service-recovery.sh"
SCHEDULED_RESTART_SCRIPT = ROOT / "deploy" / "scheduled-restart.sh"


def _extract_function(script_path: Path, name: str, next_name: str) -> str:
    source = script_path.read_text(encoding="utf-8")
    start_marker = f"{name}() {{"
    end_marker = f"\n{next_name}() {{"
    function_body = source.split(start_marker, 1)[1].split(end_marker, 1)[0]
    return f"{start_marker}{function_body}"


def _run_bash(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-s"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, **env},
        timeout=10,
    )


def _recovery_harness() -> str:
    return """
set -euo pipefail
LOG_FILE=/dev/null
recovered_services=()
source "$RECOVERY_SCRIPT_VALUE"
log() { :; }
service_status() { printf '%s\n' "$CURRENT_STATUS"; }
wait_for_service_ok() { return "$WAIT_RESULT"; }
docker() {
  printf 'docker %s\n' "$*" >> "$CALLS_FILE"
  if [[ "$1" == "restart" ]]; then return "$RESTART_RESULT"; fi
  return "$START_RESULT"
}
compose() { printf 'compose %s\n' "$*" >> "$CALLS_FILE"; }
attempt_service_recovery tgmsg-app app test-reason
printf '%s\n' "${recovered_services[*]}"
"""


def test_running_unhealthy_container_falls_back_to_force_recreate(tmp_path: Path):
    calls_file = tmp_path / "calls"
    result = _run_bash(
        _recovery_harness(),
        {
            "CALLS_FILE": str(calls_file),
            "RECOVERY_SCRIPT_VALUE": str(RECOVERY_SCRIPT),
            "CURRENT_STATUS": "running",
            "RESTART_RESULT": "1",
            "START_RESULT": "1",
            "WAIT_RESULT": "0",
        },
    )

    assert result.returncode == 0, result.stderr
    assert calls_file.read_text(encoding="utf-8").splitlines() == [
        "docker restart tgmsg-app",
        "compose up -d --force-recreate --no-build app",
    ]
    assert result.stdout.strip() == "tgmsg-app:compose-up-recreate"


def test_stopped_container_uses_start_without_recreate(tmp_path: Path):
    calls_file = tmp_path / "calls"
    result = _run_bash(
        _recovery_harness(),
        {
            "CALLS_FILE": str(calls_file),
            "RECOVERY_SCRIPT_VALUE": str(RECOVERY_SCRIPT),
            "CURRENT_STATUS": "exited",
            "RESTART_RESULT": "1",
            "START_RESULT": "0",
            "WAIT_RESULT": "0",
        },
    )

    assert result.returncode == 0, result.stderr
    assert calls_file.read_text(encoding="utf-8").splitlines() == [
        "docker start tgmsg-app",
    ]
    assert result.stdout.strip() == "tgmsg-app:docker-start"


def test_scheduled_restart_invokes_docker_compose_executable(tmp_path: Path):
    function = _extract_function(
        SCHEDULED_RESTART_SCRIPT,
        "restart_app",
        "verify_http",
    )
    app_dir = tmp_path / "app"
    bin_dir = tmp_path / "bin"
    calls_file = tmp_path / "calls"
    app_dir.mkdir()
    bin_dir.mkdir()
    docker_stub = bin_dir / "docker"
    docker_stub.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > \"$CALLS_FILE\"\n",
        encoding="utf-8",
    )
    docker_stub.chmod(0o755)
    runner = f"""
set -euo pipefail
LOG_FILE=/dev/null
APP_DIR="$APP_DIR_VALUE"
ENV_FILE=/data/tgmsg/shared/.env
RESTART_TIMEOUT_SECONDS=30
log() {{ :; }}
run_with_timeout() {{ local timeout_seconds="$1"; shift; "$@"; }}
{function}
restart_app
"""

    result = _run_bash(
        runner,
        {
            "APP_DIR_VALUE": str(app_dir),
            "CALLS_FILE": str(calls_file),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0, result.stderr
    assert calls_file.read_text(encoding="utf-8").strip() == (
        "compose --env-file /data/tgmsg/shared/.env "
        "up -d --no-build --force-recreate app"
    )
