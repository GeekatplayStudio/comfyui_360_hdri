import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import torch


OUTPUT_DIR = tempfile.mkdtemp(prefix="meshy-node-tests-")
sys.modules.setdefault(
    "folder_paths",
    types.SimpleNamespace(get_output_directory=lambda: OUTPUT_DIR),
)
SPEC = importlib.util.spec_from_file_location(
    "meshy_nodes_under_test",
    os.path.join(os.path.dirname(__file__), "..", "nodes", "meshy_nodes.py"),
)
meshy_nodes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(meshy_nodes)


class FakeResponse:
    def __init__(self, payload=None, status_code=200, content=b"model"):
        self.payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = json.dumps(payload) if payload is not None else ""
        self.content = content

    def json(self):
        return self.payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)

    def iter_content(self, chunk_size):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []
        self.responses = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append(("GET-DOWNLOAD", url, kwargs))
        return self.responses.pop(0)


class MeshyNodeTests(unittest.TestCase):
    def test_current_openapi_endpoint_and_payload(self):
        session = FakeSession()
        session.responses.append(FakeResponse({"result": "task-1"}))
        api = meshy_nodes.MeshyAPI("secret", session=session)

        task_id = api.create_text_preview(
            "robot", ai_model="latest", target_formats=["glb"]
        )

        self.assertEqual(task_id, "task-1")
        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://api.meshy.ai/openapi/v2/text-to-3d")
        self.assertEqual(kwargs["json"]["mode"], "preview")
        self.assertNotIn("negative_prompt", kwargs["json"])

    def test_refine_uses_preview_task_id(self):
        session = FakeSession()
        session.responses.append(FakeResponse({"result": "refine-1"}))
        api = meshy_nodes.MeshyAPI("secret", session=session)

        api.create_text_refine("preview-1", enable_pbr=True)

        payload = session.calls[0][2]["json"]
        self.assertEqual(
            payload,
            {"mode": "refine", "preview_task_id": "preview-1", "enable_pbr": True},
        )

    def test_image_tensor_encodes_first_batch_item(self):
        image = torch.zeros((2, 4, 3, 3), dtype=torch.float32)
        uri = meshy_nodes.image_to_data_uri(image)
        self.assertTrue(uri.startswith("data:image/png;base64,"))

    def test_download_checks_response_and_writes_model(self):
        session = FakeSession()
        session.responses.append(FakeResponse(content=b"glTF"))
        path, task_id = meshy_nodes.download_meshy_model(
            {"model_urls": {"glb": "https://cdn.example/model.glb?token=x"}},
            "../unsafe",
            session=session,
        )
        self.assertEqual(task_id, "../unsafe")
        self.assertEqual(os.path.basename(path), "meshy____unsafe.glb")
        with open(path, "rb") as model:
            self.assertEqual(model.read(), b"glTF")

    def test_failed_status_has_useful_error(self):
        session = FakeSession()
        session.responses.append(
            FakeResponse({"status": "FAILED", "task_error": {"message": "bad prompt"}})
        )
        api = meshy_nodes.MeshyAPI("secret", session=session)
        with self.assertRaisesRegex(RuntimeError, "bad prompt"):
            api.poll_task("task-1", poll_interval=0)

    def test_meshy_7_model_in_options(self):
        text_inputs = meshy_nodes.Geekatplay_Meshy_TextTo3D.INPUT_TYPES()
        self.assertIn("meshy-7", text_inputs["optional"]["ai_model"][0])
        image_inputs = meshy_nodes.Geekatplay_Meshy_ImageTo3D.INPUT_TYPES()
        self.assertIn("meshy-7", image_inputs["optional"]["ai_model"][0])

    def test_download_3mf_format(self):
        session = FakeSession()
        session.responses.append(FakeResponse(content=b"3MF_CONTENT"))
        path, task_id = meshy_nodes.download_meshy_model(
            {"model_urls": {"3mf": "https://cdn.example/model.3mf"}},
            "test_3mf",
            preferred_format="3mf",
            session=session,
        )
        self.assertTrue(path.endswith(".3mf"))
        with open(path, "rb") as model:
            self.assertEqual(model.read(), b"3MF_CONTENT")

    def test_meshy_api_key_resolution(self):
        with patch.dict(os.environ, {"MESHY_API_KEY": "env-secret-meshy"}):
            resolved = meshy_nodes.resolve_meshy_key("")
            self.assertEqual(resolved, "env-secret-meshy")


if __name__ == "__main__":
    unittest.main()
