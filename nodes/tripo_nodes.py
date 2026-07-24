"""ComfyUI nodes for the Tripo v3 API."""

import json
import os
import re
import time
from io import BytesIO
from urllib.parse import urlparse

import folder_paths
import numpy as np
import requests
import torch
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


TRIPO_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tripo_config.json")
REQUEST_TIMEOUT = (15, 120)


def load_tripo_api_key():
    """Read environment first, then the legacy config without writing new plaintext secrets."""
    environment_key = os.environ.get("TRIPO_API_KEY", "").strip()
    if environment_key:
        return environment_key
    try:
        with open(TRIPO_CONFIG_PATH, "r", encoding="utf-8") as config_file:
            return str(json.load(config_file).get("tripo_api_key", "")).strip()
    except (FileNotFoundError, OSError, ValueError):
        return ""


def resolve_tripo_key(input_value):
    value = str(input_value or "").strip()
    if value and value != "****************":
        return value
    return load_tripo_api_key()


def tensor2pil(image):
    array = image.detach().cpu().numpy()
    if array.ndim == 4:
        array = array[0]
    return Image.fromarray(np.clip(array * 255.0, 0, 255).astype(np.uint8)).convert("RGB")


def _safe_task_id(task_id):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(task_id))


class TripoAPI:
    BASE_URL = "https://openapi.tripo3d.com/v3"

    def __init__(self, api_key, session=None):
        if not api_key:
            raise ValueError("Tripo API key is required")
        self.session = session or self._make_session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
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
                method,
                f"{self.BASE_URL}/{path.lstrip('/')}",
                timeout=REQUEST_TIMEOUT,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Tripo request failed: {exc}") from exc
        if not response.ok:
            raise RuntimeError(f"Tripo API error ({response.status_code}): {response.text}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Tripo returned invalid JSON") from exc
        if payload.get("code", 0) != 0:
            message = payload.get("message") or payload.get("error_message") or payload
            raise RuntimeError(f"Tripo API error: {message}")
        return payload.get("data", payload)

    def upload_image(self, image_tensor):
        buffer = BytesIO()
        tensor2pil(image_tensor).save(buffer, format="PNG")
        buffer.seek(0)
        data = self._request(
            "POST",
            "files",
            files={"file": ("image.png", buffer, "image/png")},
        )
        return data["file_token"]

    def create_generation(self, endpoint, payload):
        return self._request("POST", f"generation/{endpoint}", json=payload)["task_id"]

    def create_animation(self, endpoint, payload):
        return self._request("POST", f"animations/{endpoint}", json=payload)

    def get_task(self, task_id):
        return self._request("GET", f"tasks/{task_id}")

    def poll_task(self, task_id, timeout=900, poll_interval=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = self.get_task(task_id)
            status = str(task.get("status", "")).lower()
            if status == "success":
                return task
            if status in {"failed", "cancelled", "banned"}:
                message = task.get("error_message") or task.get("error_code") or task
                raise RuntimeError(f"Tripo task {status}: {message}")
            time.sleep(poll_interval)
        raise TimeoutError(f"Tripo task did not finish within {timeout} seconds")

    def download_model(self, model_url, task_id, prefix="tripo"):
        extension = os.path.splitext(urlparse(model_url).path)[1].lower()
        if extension not in {".glb", ".fbx", ".obj", ".stl", ".usdz"}:
            extension = ".glb"
        output_dir = os.path.join(folder_paths.get_output_directory(), "tripo_models")
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{prefix}_{_safe_task_id(task_id)}{extension}")
        partial = filepath + ".part"
        try:
            with self.session.get(model_url, stream=True, timeout=REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                with open(partial, "wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            output.write(chunk)
            if not os.path.getsize(partial):
                raise RuntimeError("Tripo downloaded an empty model file")
            os.replace(partial, filepath)
        finally:
            if os.path.exists(partial):
                os.remove(partial)
        return filepath


class Geekatplay_Tripo_ModelGen:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_front": ("IMAGE",),
                "face_limit": ("INT", {"default": 10000, "min": 50, "max": 20000}),
                "texture": ("BOOLEAN", {"default": True}),
                "pbr": ("BOOLEAN", {"default": True}),
                "quad": ("BOOLEAN", {"default": False}),
                "auto_size": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "api_key": ("STRING", {"default": "", "password": True}),
                "image_left": ("IMAGE",),
                "image_back": ("IMAGE",),
                "image_right": ("IMAGE",),
                "model_version": (
                    ["v3.1-20260211", "P1-20260311", "v3.0-20250812"],
                    {"default": "v3.1-20260211"},
                ),
                "texture_alignment": (
                    ["original_image", "geometry"],
                    {"default": "original_image"},
                ),
                "texture_quality": (
                    ["standard", "detailed", "extreme"],
                    {"default": "detailed"},
                ),
                "geometry_quality": (
                    ["standard", "detailed"],
                    {"default": "detailed"},
                ),
                "enable_image_autofix": ("BOOLEAN", {"default": False}),
                "model_seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
                "texture_seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
                "export_uv": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("model_path", "task_id")
    FUNCTION = "generate_model"
    CATEGORY = "Geekatplay/Tripo3D"

    def generate_model(
        self, image_front, face_limit, texture, pbr, quad, auto_size, api_key="",
        image_left=None, image_back=None, image_right=None,
        model_version="v3.1-20260211", texture_alignment="original_image",
        texture_quality="detailed", geometry_quality="detailed",
        enable_image_autofix=False, model_seed=0, texture_seed=0, export_uv=True,
    ):
        tripo = TripoAPI(resolve_tripo_key(api_key))
        views = {
            "front": image_front,
            "left": image_left,
            "back": image_back,
            "right": image_right,
        }
        tokens = {name: tripo.upload_image(image) for name, image in views.items() if image is not None}
        options = {
            "model": model_version,
            "face_limit": face_limit,
            "texture": texture or pbr,
            "pbr": pbr,
            "texture_alignment": texture_alignment,
            "texture_quality": texture_quality,
            "auto_size": auto_size,
            "enable_image_autofix": enable_image_autofix,
            "export_uv": export_uv,
        }
        if model_version != "P1-20260311":
            options["geometry_quality"] = geometry_quality
            options["quad"] = quad
        if model_seed:
            options["model_seed"] = model_seed
        if texture_seed:
            options["texture_seed"] = texture_seed

        if len(tokens) > 1:
            options["inputs"] = [{name: token} for name, token in tokens.items()]
            task_id = tripo.create_generation("multiview-to-model", options)
        else:
            options["input"] = tokens["front"]
            task_id = tripo.create_generation("image-to-model", options)

        result = tripo.poll_task(task_id)
        output = result.get("output") or {}
        model_url = output.get("model_url") or output.get("pbr_model") or output.get("model")
        if not model_url:
            raise RuntimeError(f"Tripo returned no model URL. Available fields: {list(output)}")
        return tripo.download_model(model_url, task_id), task_id


class Geekatplay_Tripo_AnimateRig:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "original_task_id": ("STRING", {"default": "", "forceInput": True}),
                "animation_preset": (
                    [
                        "preset:idle", "preset:walk", "preset:run", "preset:dive",
                        "preset:climb", "preset:jump", "preset:slash", "preset:shoot",
                        "preset:hurt", "preset:fall", "preset:turn",
                        "preset:quadruped:walk",
                    ],
                    {"default": "preset:walk"},
                ),
                "rig_type": (
                    ["auto", "biped", "quadruped"],
                    {"default": "auto"},
                ),
            },
            "optional": {
                "api_key": ("STRING", {"default": "", "password": True}),
                "skeleton_spec": (["mixamo", "tripo"], {"default": "mixamo"}),
                "animate_in_place": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("rigged_model_path", "task_id")
    FUNCTION = "animate_model"
    CATEGORY = "Geekatplay/Tripo3D"

    def animate_model(
        self, original_task_id, animation_preset, rig_type, api_key="",
        skeleton_spec="mixamo", animate_in_place=False,
    ):
        if not original_task_id.strip():
            raise ValueError("Original Tripo task ID is required")
        tripo = TripoAPI(resolve_tripo_key(api_key))
        selected_rig_type = rig_type
        if rig_type == "auto":
            check = tripo.create_animation("rig-check", {"input": original_task_id.strip()})
            if check.get("riggable") is False:
                raise RuntimeError("Tripo reports that this model cannot be rigged")
            selected_rig_type = check.get("rig_type") or "biped"

        rig_data = tripo.create_animation(
            "rig",
            {
                "input": original_task_id.strip(),
                "rig_type": selected_rig_type,
                "spec": skeleton_spec,
                "out_format": "glb",
            },
        )
        rig_task_id = rig_data["task_id"]
        tripo.poll_task(rig_task_id)
        animation_data = tripo.create_animation(
            "retarget",
            {
                "input": rig_task_id,
                "animation": animation_preset,
                "out_format": "glb",
                "bake_animation": True,
                "animate_in_place": animate_in_place,
            },
        )
        animation_task_id = animation_data["task_id"]
        result = tripo.poll_task(animation_task_id)
        output = result.get("output") or {}
        model_url = output.get("model_url") or output.get("model")
        if not model_url:
            urls = output.get("model_urls") or []
            model_url = urls[0] if urls else None
        if not model_url:
            raise RuntimeError(f"Tripo returned no animated model URL: {list(output)}")
        path = tripo.download_model(model_url, animation_task_id, prefix="tripo_anim")
        return path, animation_task_id


NODE_CLASS_MAPPINGS = {
    "Geekatplay_Tripo_ModelGen": Geekatplay_Tripo_ModelGen,
    "Geekatplay_Tripo_AnimateRig": Geekatplay_Tripo_AnimateRig,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "Geekatplay_Tripo_ModelGen": "Tripo v3 Image/Multi-View to 3D",
    "Geekatplay_Tripo_AnimateRig": "Tripo v3 Auto-Rig & Animate",
}
