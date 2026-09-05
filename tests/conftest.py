"""pytest configuration and mock environment for ComfyUI modules."""

import os
import sys
import tempfile
import types

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

OUTPUT_DIR = tempfile.mkdtemp(prefix="comfyui-toolbox-test-output-")
INPUT_DIR = tempfile.mkdtemp(prefix="comfyui-toolbox-test-input-")

# Mock folder_paths
if "folder_paths" not in sys.modules:
    folder_paths_mock = types.ModuleType("folder_paths")
    folder_paths_mock.get_output_directory = lambda: OUTPUT_DIR
    folder_paths_mock.get_input_directory = lambda: INPUT_DIR
    folder_paths_mock.get_temp_directory = lambda: OUTPUT_DIR
    folder_paths_mock.get_annotated_filepath = lambda name: name
    sys.modules["folder_paths"] = folder_paths_mock


# Mock server
class _FakeRoutes:
    def _decorator(self, path):
        return lambda fn: fn

    get = post = delete = put = patch = _decorator

    def __iter__(self):
        return iter([])


if "server" not in sys.modules:
    server_mock = types.ModuleType("server")
    server_mock.PromptServer = types.SimpleNamespace(
        instance=types.SimpleNamespace(routes=_FakeRoutes())
    )
    sys.modules["server"] = server_mock

# Mock comfy and submodules
if "comfy" not in sys.modules:
    comfy_mock = types.ModuleType("comfy")
    comfy_utils = types.ModuleType("comfy.utils")
    comfy_utils.ANY = "*"
    comfy_utils.common_upscale = lambda img, w, h, method, crop: img

    comfy_mm = types.ModuleType("comfy.model_management")
    comfy_mm.unload_all_models = lambda: None
    comfy_mm.soft_empty_cache = lambda: None

    comfy_mock.utils = comfy_utils
    comfy_mock.model_management = comfy_mm

    sys.modules["comfy"] = comfy_mock
    sys.modules["comfy.utils"] = comfy_utils
    sys.modules["comfy.model_management"] = comfy_mm
