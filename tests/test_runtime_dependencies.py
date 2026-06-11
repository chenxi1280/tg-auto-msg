import importlib.util
import unittest


class RuntimeDependencyTests(unittest.TestCase):
    def test_telethon_proxy_dependency_is_installed(self):
        self.assertIsNotNone(importlib.util.find_spec("python_socks"))
