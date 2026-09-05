import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import torch

OUTPUT_DIR = tempfile.mkdtemp(prefix="hitem3d-node-tests-")
sys.modules.setdefault(
    "folder_paths",
    types.SimpleNamespace(get_output_directory=lambda: OUTPUT_DIR),
)
SPEC = importlib.util.spec_from_file_location(
    "hitem3d_nodes_under_test",
    os.path.join(os.path.dirname(__file__), "..", "nodes", "hitem3d_nodes.py"),
)
hitem3d_nodes = importlib.util.module_from_spec(SPEC)
sys.modules["hitem3d_nodes_under_test"] = hitem3d_nodes
SPEC.loader.exec_module(hitem3d_nodes)

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

class HiTem3DTests(unittest.TestCase):
    @patch("requests.post")
    def test_get_token(self, mock_post):
        mock_post.return_value = FakeResponse({
            "code": 200,
            "data": {
                "accessToken": "test-token-123"
            }
        })
        client = hitem3d_nodes.HiTem3DAPIClient("access", "secret")
        token = client._get_token()
        self.assertEqual(token, "test-token-123")
        self.assertEqual(client.access_token, "test-token-123")
        
        # Verify subsequent call uses cached token if not expired
        client.token_expires_at = hitem3d_nodes.time.time() + 7200
        mock_post.reset_mock()
        token2 = client._get_token()
        self.assertEqual(token2, "test-token-123")
        mock_post.assert_not_called()

    @patch("requests.post")
    def test_create_task_single_view(self, mock_post):
        client = hitem3d_nodes.HiTem3DAPIClient("access", "secret")
        client.access_token = "dummy-token"
        client.token_expires_at = hitem3d_nodes.time.time() + 7200
        
        mock_post.return_value = FakeResponse({
            "code": 200,
            "data": {
                "task_id": "hitem-task-999"
            }
        })
        
        task_id = client.create_task(
            front_image_bytes=b"front_img",
            model="hitem3dv2.1",
            resolution="1536fast",
            pbr=True
        )
        self.assertEqual(task_id, "hitem-task-999")
        
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.hitem3d.ai/open-api/v1/submit-task")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer dummy-token")
        self.assertEqual(kwargs["data"]["model"], "hitem3dv2.1")
        self.assertEqual(kwargs["data"]["resolution"], "1536fast")
        self.assertEqual(kwargs["data"]["pbr"], "1")
        
        files = kwargs["files"]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0][0], "images")
        self.assertEqual(files[0][1][0], "front.jpg")
        self.assertEqual(files[0][1][1], b"front_img")

    @patch("requests.post")
    def test_create_task_multi_view(self, mock_post):
        client = hitem3d_nodes.HiTem3DAPIClient("access", "secret")
        client.access_token = "dummy-token"
        client.token_expires_at = hitem3d_nodes.time.time() + 7200
        
        mock_post.return_value = FakeResponse({
            "code": 200,
            "data": {
                "task_id": "hitem-task-multi"
            }
        })
        
        task_id = client.create_task(
            front_image_bytes=b"front_img",
            back_image_bytes=b"back_img",
            model="hitem3dv2.1",
            resolution="1536fast",
            pbr=False
        )
        self.assertEqual(task_id, "hitem-task-multi")
        
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"]["multi_images_bit"], "1100")
        self.assertEqual(kwargs["data"]["pbr"], "0")
        
        files = kwargs["files"]
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0][0], "multi_images")
        self.assertEqual(files[0][1][0], "front.jpg")
        self.assertEqual(files[0][1][1], b"front_img")
        self.assertEqual(files[1][0], "multi_images")
        self.assertEqual(files[1][1][0], "back.jpg")
        self.assertEqual(files[1][1][1], b"back_img")

    @patch("requests.get")
    def test_query_task(self, mock_get):
        client = hitem3d_nodes.HiTem3DAPIClient("access", "secret")
        client.access_token = "dummy-token"
        client.token_expires_at = hitem3d_nodes.time.time() + 7200
        
        mock_get.return_value = FakeResponse({
            "code": 200,
            "data": {
                "task_id": "hitem-task-999",
                "state": "success",
                "url": "https://example.com/mesh.glb"
            }
        })
        
        data = client.query_task("hitem-task-999")
        self.assertEqual(data["state"], "success")
        self.assertEqual(data["url"], "https://example.com/mesh.glb")
        
        mock_get.assert_called_once_with(
            "https://api.hitem3d.ai/open-api/v1/query-task",
            headers={"Authorization": "Bearer dummy-token", "Accept": "*/*"},
            params={"task_id": "hitem-task-999"},
            timeout=30
        )

    @patch("requests.get")
    @patch("requests.post")
    def test_generate_flow(self, mock_post, mock_get):
        # Handle the post calls (1st for token, 2nd for submit-task)
        def post_side_effect(url, **kwargs):
            if "auth/token" in url:
                return FakeResponse({
                    "code": 200,
                    "data": {
                        "accessToken": "tok-123"
                    }
                })
            elif "submit-task" in url:
                return FakeResponse({
                    "code": 200,
                    "data": {
                        "task_id": "task-abc"
                    }
                })
            return FakeResponse(status_code=404)
        mock_post.side_effect = post_side_effect

        # Handle the get calls (1st for query-task, 2nd for downloading stream)
        query_resp = FakeResponse({
            "code": 200,
            "data": {
                "task_id": "task-abc",
                "state": "success",
                "url": "https://example.com/mesh.glb"
            }
        })
        download_resp = FakeResponse(status_code=200, content=b"fake-glb-mesh-data")
        
        def get_side_effect(url, **kwargs):
            if "query-task" in url:
                return query_resp
            elif "mesh.glb" in url:
                return download_resp
            return FakeResponse(status_code=404)
        mock_get.side_effect = get_side_effect

        generator = hitem3d_nodes.Geekatplay_HiTem3D_Gen()
        front_image = torch.zeros((1, 8, 8, 3))
        
        with patch("hitem3d_nodes_under_test.time.sleep", return_value=None):
            filepath, task_id = generator.generate(
                front_image=front_image,
                model="hitem3dv2.1",
                resolution="1536fast",
                face_count=1000000,
                output_format="glb",
                generation_type="all_in_one",
                pbr=True,
                api_key="access:secret"
            )
            
        self.assertEqual(task_id, "task-abc")
        self.assertTrue(filepath.endswith("hitem3d_task-abc.glb"))
        self.assertTrue(os.path.exists(filepath))
        with open(filepath, "rb") as f:
            self.assertEqual(f.read(), b"fake-glb-mesh-data")
            
        os.remove(filepath)

    def test_direct_bearer_token(self):
        client = hitem3d_nodes.HiTem3DAPIClient(token="hi3d_live_direct_token")
        token = client._get_token()
        self.assertEqual(token, "hi3d_live_direct_token")

    @patch("requests.post")
    def test_create_task_v3_and_2048(self, mock_post):
        client = hitem3d_nodes.HiTem3DAPIClient(token="direct_token")
        mock_post.return_value = FakeResponse({
            "code": 200,
            "data": {
                "task_id": "hitem-v3-task"
            }
        })
        task_id = client.create_task(
            front_image_bytes=b"front_img",
            model="hitem3dv3.0",
            resolution="2048",
            pbr=True,
            output_format=6
        )
        self.assertEqual(task_id, "hitem-v3-task")
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"]["model"], "hitem3dv3.0")
        self.assertEqual(kwargs["data"]["resolution"], "2048")
        self.assertEqual(kwargs["data"]["pbr"], "1")
        self.assertEqual(kwargs["data"]["format"], "6")

    def test_resolve_hitem3d_key(self):
        with patch.dict(os.environ, {"HI3D_API_KEY": "env-hi3d-key"}):
            self.assertEqual(hitem3d_nodes.resolve_hitem3d_key(""), "env-hi3d-key")


if __name__ == "__main__":
    unittest.main()
