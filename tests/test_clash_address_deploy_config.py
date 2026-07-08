from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class ClashAddressDeployConfigTests(unittest.TestCase):
    def test_app_container_has_proxy_runtime_mounts(self):
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn(
            "${CLASH_ADDRESS_CONFIG_DIR:-/data/infra/sing-box}:${CLASH_ADDRESS_CONFIG_DIR:-/data/infra/sing-box}",
            compose,
        )
        self.assertIn(
            "${CLASH_ADDRESS_COMPOSE_DIR:-/data/infra/compose}:${CLASH_ADDRESS_COMPOSE_DIR:-/data/infra/compose}:ro",
            compose,
        )
        self.assertIn("/var/run/docker.sock:/var/run/docker.sock", compose)

    def test_backend_image_installs_docker_cli_for_apply_command(self):
        dockerfile = (REPO_ROOT / "docker" / "Dockerfile.backend").read_text(encoding="utf-8")

        self.assertIn("download.docker.com/linux/static", dockerfile)
        self.assertIn("/usr/local/bin/docker", dockerfile)
        self.assertIn("26.1.3", dockerfile)

    def test_backend_image_installs_compose_plugin_for_apply_command(self):
        dockerfile = (REPO_ROOT / "docker" / "Dockerfile.backend").read_text(encoding="utf-8")

        self.assertIn("github.com/docker/compose/releases/download", dockerfile)
        self.assertIn("/usr/local/lib/docker/cli-plugins/docker-compose", dockerfile)

    def test_backend_image_has_yaml_dependency_for_sing_box_renderer(self):
        requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("PyYAML", requirements)
