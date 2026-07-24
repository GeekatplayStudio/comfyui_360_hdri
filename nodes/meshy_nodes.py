"""ComfyUI nodes for Meshy's public REST API."""

import base64
import os
import re
import time
from io import BytesIO
from urllib.parse import urlparse

import folder_paths
import numpy as np
import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


REQUEST_TIMEOUT = (15, 120)
SUPPORTED_MODEL_FORMATS = ("glb", "fbx", "obj", "stl", "usdz", "3mf")


def tensor2pil(image):
    """Convert the first ComfyUI image in a batch to an RGB PIL image."""
    array = image.detach().cpu().numpy()
    if array.ndim == 4:
        array = array[0]
    array = np.clip(array * 255.0, 0, 255).astype(np.uint8)
    pil_image = Image.fromarray(array)
    return pil_image.convert("RGB")


def image_to_data_uri(image_tensor):
    buffered = BytesIO()
    tensor2pil(image_tensor).save(buffered, format="PNG")
    encoded = base64.b64encode(buffered.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _model_extension(model_url, preferred_format):
    extension = os.path.splitext(urlparse(model_url).path)[1].lower().lstrip(".")
    return extension if extension in SUPPORTED_MODEL_FORMATS else preferred_format


def download_meshy_model(result, task_id, preferred_format="glb", session=None):
    model_urls = result.get("model_urls") or {}
    ordered_formats = (preferred_format,) + tuple(
        fmt for fmt in SUPPORTED_MODEL_FORMATS if fmt != preferred_format
    )
    model_url = next((model_urls.get(fmt) for fmt in ordered_formats if model_urls.get(fmt)), None)
    if not model_url:
        raise RuntimeError(
            "Meshy returned no supported model URL. "
            f"Available formats: {', '.join(model_urls) or 'none'}"
        )

    output_dir = os.path.join(folder_paths.get_output_directory(), "meshy_models")
    os.makedirs(output_dir, exist_ok=True)
    safe_task_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(task_id))
    extension = _model_extension(model_url, preferred_format)
    filepath = os.path.join(output_dir, f"meshy_{safe_task_id}.{extension}")
    partial_path = filepath + ".part"

    client = session or requests
    try:
        with client.get(model_url, stream=True, timeout=REQUEST_TIMEOUT) as response:
            response.raise_for_status()
            with open(partial_path, "wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)
        if not os.path.getsize(partial_path):
            raise RuntimeError("Meshy downloaded an empty model file")
        os.replace(partial_path, filepath)
    finally:
        if os.path.exists(partial_path):
            os.remove(partial_path)

    return filepath, str(task_id)


class MeshyAPI:
    BASE_URL = "https://api.meshy.ai/openapi"

    def __init__(self, api_key, session=None):
        if not api_key or not api_key.strip():
            raise ValueError("Meshy API key is required")
        self.session = session or self._make_session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key.strip()}",
                "Content-Type": "application/json",
                "User-Agent": "ComfyUI-Blender-Toolbox/1.2",
            }
        )

    @staticmethod
    def _make_session():
        session = requests.Session()
        retry = Retry(
            total=4,
            connect=4,
            read=2,
            status=4,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(("GET",)),
            respect_retry_after_header=True,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return session

    def _request(self, method, path, **kwargs):
        try:
            response = self.session.request(
                method, f"{self.BASE_URL}/{path.lstrip('/')}", timeout=REQUEST_TIMEOUT, **kwargs
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Meshy request failed: {exc}") from exc
        if not response.ok:
            try:
                error = response.json()
                message = error.get("message") or error.get("error") or response.text
            except ValueError:
                message = response.text
            raise RuntimeError(f"Meshy API error ({response.status_code}): {message}")
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError("Meshy returned an invalid JSON response") from exc

    def create_text_preview(self, prompt, **kwargs):
        payload = {"mode": "preview", "prompt": prompt, **kwargs}
        return self._request("POST", "v2/text-to-3d", json=payload)["result"]

    def create_text_refine(self, preview_task_id, **kwargs):
        payload = {"mode": "refine", "preview_task_id": preview_task_id, **kwargs}
        return self._request("POST", "v2/text-to-3d", json=payload)["result"]

    def create_image_to_3d_task(self, image_uri, **kwargs):
        payload = {"image_url": image_uri, **kwargs}
        return self._request("POST", "v1/image-to-3d", json=payload)["result"]

    def get_task(self, task_id, task_type="text-to-3d"):
        version = "v2" if task_type == "text-to-3d" else "v1"
        data = self._request("GET", f"{version}/{task_type}/{task_id}")
        return data.get("result", data)

    def poll_task(self, task_id, task_type="text-to-3d", timeout=900, poll_interval=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task_data = self.get_task(task_id, task_type)
            status = str(task_data.get("status", "")).upper()
            if status == "SUCCEEDED":
                return task_data
            if status in {"FAILED", "EXPIRED", "CANCELED"}:
                error = task_data.get("task_error") or task_data.get("error") or "Unknown error"
                raise RuntimeError(f"Meshy task {status.lower()}: {error}")
            time.sleep(poll_interval)
        raise TimeoutError(f"Meshy task did not finish within {timeout} seconds")


class Geekatplay_Meshy_TextTo3D:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": "a futuristic sci-fi helmet"}),
                "mode": (["preview", "refine"], {"default": "preview"}),
                # Retained to keep existing workflows loadable. Meshy 6 ignores this legacy field.
                "art_style": (["realistic", "cartoon", "low-poly", "voxel"], {"default": "realistic"}),
            },
            "optional": {
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
                "api_key": ("STRING", {"multiline": False, "default": "", "password": True, "label": "Meshy API Key"}),
                "ai_model": (["latest", "meshy-6", "meshy-5"], {"default": "latest"}),
                "model_type": (["standard", "lowpoly"], {"default": "standard"}),
                "topology": (["triangle", "quad"], {"default": "triangle"}),
                "target_polycount": ("INT", {"default": 30000, "min": 100, "max": 300000}),
                "should_remesh": ("BOOLEAN", {"default": False}),
                "symmetry_mode": (["auto", "on", "off"], {"default": "auto"}),
                "pose_mode": (["default", "a-pose", "t-pose"], {"default": "default"}),
                "should_rig": ("BOOLEAN", {"default": False, "label": "Legacy (not supported)"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "enable_pbr": ("BOOLEAN", {"default": True}),
                "hd_texture": ("BOOLEAN", {"default": False}),
                "texture_prompt": ("STRING", {"multiline": True, "default": ""}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("model_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = "Geekatplay/Meshy"

    def generate(
        self, prompt, mode, art_style, negative_prompt="", api_key="", ai_model="latest",
        topology="triangle", target_polycount=30000, should_remesh=False,
        symmetry_mode="auto", pose_mode="default", should_rig=False, seed=0,
        model_type="standard", enable_pbr=True, hd_texture=False, texture_prompt="",
    ):
        del art_style, negative_prompt, symmetry_mode, should_rig, seed
        if not prompt.strip():
            raise ValueError("Meshy prompt cannot be empty")
        meshy = MeshyAPI(api_key)
        preview_options = {
            "model_type": model_type,
            "ai_model": ai_model,
            "should_remesh": should_remesh,
            "target_formats": ["glb"],
        }
        if should_remesh:
            preview_options.update(topology=topology, target_polycount=target_polycount)
        if pose_mode != "default":
            preview_options["pose_mode"] = pose_mode

        preview_id = meshy.create_text_preview(prompt.strip(), **preview_options)
        preview_result = meshy.poll_task(preview_id)
        if mode == "preview":
            return download_meshy_model(preview_result, preview_id, session=meshy.session)

        refine_options = {
            "ai_model": ai_model,
            "enable_pbr": enable_pbr,
            "hd_texture": hd_texture,
            "target_formats": ["glb"],
        }
        if texture_prompt.strip():
            refine_options["texture_prompt"] = texture_prompt.strip()
        refine_id = meshy.create_text_refine(preview_id, **refine_options)
        refine_result = meshy.poll_task(refine_id)
        return download_meshy_model(refine_result, refine_id, session=meshy.session)


class Geekatplay_Meshy_ImageTo3D:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "enable_pbr": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "api_key": ("STRING", {"multiline": False, "default": "", "password": True, "label": "Meshy API Key"}),
                "model_type": (["standard", "smart-topology"], {"default": "standard"}),
                "ai_model": (["latest", "meshy-6", "meshy-5", "meshy-t2", "meshy-t1"], {"default": "latest"}),
                "topology": (["triangle", "quad"], {"default": "triangle"}),
                "target_polycount": ("INT", {"default": 30000, "min": 100, "max": 300000}),
                "should_remesh": ("BOOLEAN", {"default": False}),
                "should_texture": ("BOOLEAN", {"default": True}),
                "symmetry_mode": (["auto", "on", "off"], {"default": "auto"}),
                "pose_mode": (["default", "a-pose", "t-pose"], {"default": "default"}),
                "should_rig": ("BOOLEAN", {"default": False, "label": "Legacy (not supported)"}),
                "texture_prompt": ("STRING", {"multiline": True, "default": ""}),
                "hd_texture": ("BOOLEAN", {"default": False}),
                "remove_lighting": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("model_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = "Geekatplay/Meshy"

    def generate(
        self, image, enable_pbr, api_key="", model_type="standard", ai_model="latest",
        topology="triangle", target_polycount=30000, should_remesh=False,
        should_texture=True, symmetry_mode="auto", pose_mode="default",
        should_rig=False, texture_prompt="", hd_texture=False, remove_lighting=True,
    ):
        del symmetry_mode, should_rig
        meshy = MeshyAPI(api_key)
        if model_type == "smart-topology" and ai_model not in {"meshy-t1", "meshy-t2"}:
            ai_model = "meshy-t2"
        elif model_type == "standard" and ai_model in {"meshy-t1", "meshy-t2"}:
            ai_model = "latest"
        options = {
            "model_type": model_type,
            "ai_model": ai_model,
            "enable_pbr": enable_pbr,
            "should_texture": should_texture,
            "hd_texture": hd_texture,
            "remove_lighting": remove_lighting,
            "target_formats": ["glb"],
        }
        if model_type != "smart-topology":
            options["should_remesh"] = should_remesh
            if should_remesh:
                options.update(topology=topology, target_polycount=target_polycount)
        elif ai_model == "meshy-t2":
            options["target_polycount"] = target_polycount
        if pose_mode != "default":
            options["pose_mode"] = pose_mode
        if texture_prompt.strip():
            options["texture_prompt"] = texture_prompt.strip()

        task_id = meshy.create_image_to_3d_task(image_to_data_uri(image), **options)
        result = meshy.poll_task(task_id, "image-to-3d")
        return download_meshy_model(result, task_id, session=meshy.session)


NODE_CLASS_MAPPINGS = {
    "Geekatplay_Meshy_TextTo3D": Geekatplay_Meshy_TextTo3D,
    "Geekatplay_Meshy_ImageTo3D": Geekatplay_Meshy_ImageTo3D,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Geekatplay_Meshy_TextTo3D": "Meshy Text to 3D (Geekatplay)",
    "Geekatplay_Meshy_ImageTo3D": "Meshy Image to 3D (Geekatplay)",
}
