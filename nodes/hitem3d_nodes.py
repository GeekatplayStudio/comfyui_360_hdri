import requests
import json
import time
import os
import folder_paths
import numpy as np
import base64
from io import BytesIO
from PIL import Image
import torch

def tensor2pil(image):
    return Image.fromarray(np.clip(255. * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))

def tensor_to_bytes(tensor, format="JPEG"):
    pil_image = tensor2pil(tensor)
    buffer = BytesIO()
    pil_image.save(buffer, format=format)
    return buffer.getvalue()


def load_hitem3d_api_key():
    """Check environment variables HI3D_API_KEY, HITEM3D_API_KEY, and OS keyring."""
    for env_var in ("HI3D_API_KEY", "HITEM3D_API_KEY"):
        val = os.environ.get(env_var, "").strip()
        if val:
            return val
    try:
        try:
            from .geekatplay_key_manager import get_key
        except (ImportError, ValueError):
            from nodes.geekatplay_key_manager import get_key
        keyring_key = get_key("Hi3D") or get_key("HiTem3D") or get_key("hi3d") or get_key("hitem3d")
        if keyring_key:
            return keyring_key.strip()
    except Exception:
        pass
    return ""


def resolve_hitem3d_key(input_value):
    value = str(input_value or "").strip()
    if value and value != "****************":
        return value
    return load_hitem3d_api_key()


class HiTem3DAPIClient:
    def __init__(self, access_key=None, secret_key=None, token=None, base_url="https://api.hitem3d.ai"):
        self.access_key = access_key
        self.secret_key = secret_key
        self.base_url = (base_url or "https://api.hitem3d.ai").rstrip('/')
        self.access_token = token
        self.token_expires_at = time.time() + 365 * 86400 if token else 0

    def _get_basic_auth_header(self):
        credentials = f"{self.access_key}:{self.secret_key}"
        encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
        return f"Basic {encoded_credentials}"

    def _get_token(self):
        current_time = time.time()
        if self.access_token and current_time < self.token_expires_at - 3600:
            return self.access_token

        if not self.access_key or not self.secret_key:
            if self.access_token:
                return self.access_token
            raise Exception("Hi3D / HiTem3D credentials missing. Provide an API token or 'AccessKey:SecretKey'.")

        url = f"{self.base_url}/open-api/v1/auth/token"
        headers = {
            'Authorization': self._get_basic_auth_header(),
            'Content-Type': 'application/json',
            'Accept': '*/*'
        }

        try:
            response = requests.post(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            if data.get('code') == 200:
                self.access_token = data['data']['accessToken']
                self.token_expires_at = current_time + 24 * 3600
                return self.access_token
            else:
                raise Exception(f"Token request failed: {data.get('msg', 'Unknown error')}")
        except Exception as e:
            raise Exception(f"Failed to get HiTem3D access token: {str(e)}")

    def create_task(self, front_image_bytes, back_image_bytes=None, left_image_bytes=None, right_image_bytes=None,
                    model="hitem3dv3.0", resolution="1536fast", face_count=1000000,
                    output_format=2, request_type=3, pbr=True):
        
        token = self._get_token()
        url = f"{self.base_url}/open-api/v1/submit-task"
        headers = {'Authorization': f'Bearer {token}', 'Accept': '*/*'}

        data = {
            'request_type': str(request_type),
            'model': model,
            'resolution': str(resolution),
            'face': str(face_count),
            'format': str(output_format)
        }
        if model in {"hitem3dv3.0", "hitem3dv2.0", "hitem3dv2.1", "scene-portraitv2.0", "scene-portraitv2.1"}:
            data["pbr"] = "1" if pbr else "0"

        files = []
        # Multi-view check logic
        multi_images = [img for img in [front_image_bytes, back_image_bytes, left_image_bytes, right_image_bytes] if img is not None]

        if len(multi_images) > 1:
            view_names = ['front', 'back', 'left', 'right']
            images_list = [front_image_bytes, back_image_bytes, left_image_bytes, right_image_bytes]
            for i, img_bytes in enumerate(images_list):
                if img_bytes is not None:
                    files.append(('multi_images', (f'{view_names[i]}.jpg', img_bytes, 'image/jpeg')))
            data["multi_images_bit"] = "".join("1" if image is not None else "0" for image in images_list)
        else:
            files.append(('images', ('front.jpg', front_image_bytes, 'image/jpeg')))

        response = requests.post(url, headers=headers, files=files, data=data, timeout=120)
        
        if response.status_code != 200:
            raise Exception(f"HiTem3D Task Submit Failed: {response.text}")
            
        result = response.json()
        if result.get('code') == 200:
            return result['data']['task_id']
        else:
             msg = result.get('msg', 'Unknown Error')
             if 'balance is not enough' in msg.lower():
                 msg = "Insufficient balance in HiTem3D account."
             raise Exception(f"HiTem3D Error ({result.get('code')}): {msg}")

    def query_task(self, task_id):
        token = self._get_token()
        url = f"{self.base_url}/open-api/v1/query-task"
        headers = {'Authorization': f'Bearer {token}', 'Accept': '*/*'}
        params = {'task_id': task_id}
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code != 200:
             raise Exception(f"Query Failed: {response.text}")
             
        result = response.json()
        if result.get('code') == 200:
            return result['data']
        else:
            raise Exception(f"Task Query Error: {result.get('msg')}")

    def poll_task(self, task_id, timeout=900):
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                data = self.query_task(task_id)
                state = data.get('state', '').lower()
                
                if state == 'success':
                    return data
                elif state == 'failed':
                    raise Exception(f"HiTem3D Task Failed: {task_id}")
                
                time.sleep(5)
            except Exception as e:
                if "Failed" in str(e): raise e
                time.sleep(5)
                
        raise Exception("HiTem3D Timeout")

class Geekatplay_HiTem3D_Gen:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "front_image": ("IMAGE",),
                "model": (["hitem3dv3.0", "hitem3dv2.1", "hitem3dv2.0", "hitem3dv1.5", "scene-portraitv2.1", "scene-portraitv2.0", "scene-portraitv1.5"], {"default": "hitem3dv3.0"}),
                "resolution": (["2048", "1536profast", "1536pro", "1536fast", "1536", "1024", "512"], {"default": "1536fast"}),
                "face_count": ("INT", {"default": 1000000, "min": 100000, "max": 2000000, "step": 10000}),
                "output_format": (["glb", "obj", "stl", "fbx", "usdz", "3mf"], {"default": "glb"}),
                "generation_type": (["geometry_only", "staged", "all_in_one"], {"default": "all_in_one"}),
                "pbr": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "back_image": ("IMAGE",),
                "left_image": ("IMAGE",),
                "right_image": ("IMAGE",),
                "api_key": ("STRING", {"multiline": False, "default": "", "password": True, "label": "Hi3D / HiTem3D Key (Bearer Token or AccessKey:SecretKey)"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("model_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = "Geekatplay/HiTem3D"

    def generate(self, front_image, model, resolution, face_count, output_format, generation_type, 
                 pbr=True, back_image=None, left_image=None, right_image=None, api_key=""):
        
        resolved_key = resolve_hitem3d_key(api_key)
        if not resolved_key:
            raise Exception("Invalid Hi3D/HiTem3D API Key. Must be Bearer Token or 'AccessKey:SecretKey'. Use Credential Manager or set HI3D_API_KEY.")
            
        if ":" in resolved_key:
            access_key, secret_key = resolved_key.split(":", 1)
            client = HiTem3DAPIClient(access_key=access_key.strip(), secret_key=secret_key.strip())
        else:
            client = HiTem3DAPIClient(token=resolved_key.strip())
        
        # Prepare params
        fmt_map = {"obj": 1, "glb": 2, "stl": 3, "fbx": 4, "usdz": 5, "3mf": 6}
        gen_map = {"geometry_only": 1, "staged": 2, "all_in_one": 3}
        
        # Prepare Images
        front_bytes = tensor_to_bytes(front_image)
        back_bytes = tensor_to_bytes(back_image) if back_image is not None else None
        left_bytes = tensor_to_bytes(left_image) if left_image is not None else None
        right_bytes = tensor_to_bytes(right_image) if right_image is not None else None
        
        print(f"Submitting HiTem3D Task ({model})...")
        task_id = client.create_task(
            front_bytes, back_bytes, left_bytes, right_bytes,
            model=model,
            resolution=resolution,
            face_count=face_count,
            output_format=fmt_map.get(output_format, 2),
            request_type=gen_map.get(generation_type, 3),
            pbr=pbr,
        )
        print(f"Task ID: {task_id}")
        
        result = client.poll_task(task_id)
        
        # Download
        model_url = (
            result.get('url')
            or result.get('model_url')
            or result.get('mesh_url')
            or result.get('download_url')
        )
        if not model_url and isinstance(result.get('data'), dict):
            inner = result['data']
            model_url = (
                inner.get('url')
                or inner.get('model_url')
                or inner.get('mesh_url')
                or inner.get('download_url')
            )
             
        if not model_url:
            raise Exception(f"No model URL found in HiTem3D response: {list(result.keys())}")

        output_dir = folder_paths.get_output_directory()
        hitem_dir = os.path.join(output_dir, "hitem3d_models")
        if not os.path.exists(hitem_dir):
            os.makedirs(hitem_dir)
            
        filename = f"hitem3d_{task_id}.{output_format}"
        filepath = os.path.join(hitem_dir, filename)
        
        print(f"Downloading model to {filepath}...")
        partial_path = filepath + ".part"
        try:
            with requests.get(model_url, stream=True, timeout=(15, 120)) as resp:
                resp.raise_for_status()
                with open(partial_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
            if not os.path.getsize(partial_path):
                raise RuntimeError("HiTem3D downloaded an empty model file")
            os.replace(partial_path, filepath)
        finally:
            if os.path.exists(partial_path):
                os.remove(partial_path)
            
        return (filepath, task_id)

NODE_CLASS_MAPPINGS = {
    "Geekatplay_HiTem3D_Gen": Geekatplay_HiTem3D_Gen
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Geekatplay_HiTem3D_Gen": "HiTem3D Generator (Geekatplay)"
}
