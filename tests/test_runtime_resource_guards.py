from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_app_container_has_memory_and_log_isolation_defaults():
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'mem_limit: "${TGMSG_APP_MEMORY_LIMIT:-1g}"' in compose
    assert 'max-size: "${TGMSG_APP_LOG_MAX_SIZE:-50m}"' in compose
    assert 'max-file: "${TGMSG_APP_LOG_MAX_FILES:-3}"' in compose
