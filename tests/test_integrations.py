import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import torch


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT = tempfile.mkdtemp(prefix="toolbox-integrations-")
sys.modules.setdefault(
    "folder_paths",
    types.SimpleNamespace(get_output_directory=lambda: OUTPUT),
)


class FakeRoutes:
    def _decorator(self, path):
        return lambda function: function

    get = post = delete = _decorator


sys.modules.setdefault(
    "server",
    types.SimpleNamespace(
        PromptServer=types.SimpleNamespace(
            instance=types.SimpleNamespace(routes=FakeRoutes())
        )
    ),
)


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relative_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tripo = load_module("tripo_under_test", "nodes/tripo_nodes.py")
credentials = load_module(
    "credentials_under_test", "nodes/geekatplay_key_manager.py"
)


class FakeResponse:
    ok = True
    status_code = 200
    text = ""

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse(self.responses.pop(0))


class TripoV3Tests(unittest.TestCase):
    def test_upload_uses_v3_files_endpoint(self):
        session = FakeSession([{"code": 0, "data": {"file_token": "file-1"}}])
        api = tripo.TripoAPI("secret", session=session)
        token = api.upload_image(torch.zeros((1, 8, 8, 3)))
        self.assertEqual(token, "file-1")
        self.assertEqual(session.calls[0][1], "https://openapi.tripo3d.com/v3/files")

    def test_generation_and_task_query_endpoints(self):
        session = FakeSession(
            [
                {"code": 0, "data": {"task_id": "task-1"}},
                {"code": 0, "data": {"status": "success", "output": {}}},
            ]
        )
        api = tripo.TripoAPI("secret", session=session)
        task_id = api.create_generation("image-to-model", {"input": "file-1"})
        result = api.poll_task(task_id, poll_interval=0)
        self.assertEqual(result["status"], "success")
        self.assertEqual(
            session.calls[0][1],
            "https://openapi.tripo3d.com/v3/generation/image-to-model",
        )
        self.assertEqual(
            session.calls[1][1],
            "https://openapi.tripo3d.com/v3/tasks/task-1",
        )


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        credentials.KEY_INDEX_PATH = os.path.join(self.temp_dir.name, "index.json")
        credentials.LEGACY_STORE_PATH = os.path.join(self.temp_dir.name, "legacy.enc")
        self.vault = {}
        self.patchers = [
            patch.object(
                credentials.keyring,
                "set_password",
                side_effect=lambda service, name, value: self.vault.__setitem__(name, value),
            ),
            patch.object(
                credentials.keyring,
                "get_password",
                side_effect=lambda service, name: self.vault.get(name),
            ),
            patch.object(
                credentials.keyring,
                "delete_password",
                side_effect=lambda service, name: self.vault.pop(name, None),
            ),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()
        self.temp_dir.cleanup()

    def test_index_never_contains_secret(self):
        credentials.save_key("Meshy", "super-secret")
        self.assertEqual(credentials.get_key("Meshy"), "super-secret")
        with open(credentials.KEY_INDEX_PATH, encoding="utf-8") as index:
            index_data = index.read()
        self.assertIn("Meshy", index_data)
        self.assertNotIn("super-secret", index_data)

    def test_delete_removes_vault_and_index_entries(self):
        credentials.save_key("Tripo", "token")
        credentials.delete_key("Tripo")
        self.assertEqual(credentials.get_key("Tripo"), "")
        self.assertNotIn("Tripo", credentials.list_keys())


if __name__ == "__main__":
    unittest.main()
