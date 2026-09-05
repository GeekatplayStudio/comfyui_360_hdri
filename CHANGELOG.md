# Changelog

## 2.1.0

- **Tripo3D API Update**:
  - Added support for `P2-20260801` (flagship quad topology, game-ready model) and `v2.5-20250123`.
  - Added automatic fallback between `openapi.tripo3d.com` and `openapi.tripo3d.ai` endpoints.
  - Added OS Keyring (`get_key("Tripo")`) and `TRIPO_API_KEY` environment variable resolution.
- **Meshy API Update**:
  - Added support for `meshy-7` high-fidelity 3D generation model in Text-to-3D and Image-to-3D.
  - Added `3mf` format download and export support.
  - Added OS Keyring (`get_key("Meshy")`) and `MESHY_API_KEY` environment variable resolution.
- **Hi3D / HiTem3D API Update**:
  - Added `hitem3dv3.0` high-precision model (2048³ voxel geometry) and `2048` resolution option.
  - Added `3mf` slicer-ready format export for 3D printing workflows.
  - Added dual authentication: direct Bearer token (e.g., `hi3d_live_...` or single tokens) in addition to legacy `AccessKey:SecretKey`.
  - Added OS Keyring (`get_key("Hi3D")` / `get_key("HiTem3D")`) and `HI3D_API_KEY`/`HITEM3D_API_KEY` environment variable resolution.
  - Improved model URL and download endpoint resolution across API updates.
- **Blender 4.5 & 5.0 Compatibility**:
  - Implemented dynamic Blender Foundation directory scanning, automatically selecting the newest installed version (including Blender 5.0 and Blender 4.5).
  - Modernized `trimesh` Scene geometry extraction (`to_geometry()` with fallback).
  - Bumped Blender Sync addon `bl_info` to `(2, 1, 0)` with verified Blender 4.x/5.0 shader mappings.
- **Workflows & Testing**:
  - Updated all workflows (`Geekatplay_Tripo_3D_Workflow.json`, `Geekatplay_HiTem3D_Workflow.json`, `Geekatplay_Meshy_3D_Workflow.json`) with latest recommended model defaults.
  - Added `tests/conftest.py` providing complete offline ComfyUI environment mocking.
  - Expanded test coverage across all integrations to 32 passing unit tests.

## 2.0.0

- Migrated API credentials from reversible file obfuscation to the operating-system credential vault.
- Added automatic migration of legacy credentials and password-style node inputs.
- Rebuilt the credential-manager frontend with in-place refresh, error notifications, and protected secret entry.
- Upgraded Tripo integration from v2 to v3, including current file upload, generation, task, rigging, and animation endpoints.
- Added Tripo H3.1 and P1 models, current quality controls, deterministic seeds, and expanded animation presets.
- Corrected Meshy OpenAPI endpoints and implemented its required Text-to-3D preview/refine sequence.
- Added Meshy 6, Smart Topology, PBR, HD texture, lighting removal, and safer model downloads.
- Added HiTem3D 2.1 and Scene Portrait 2.1, current resolution modes, PBR, USDZ, and multi-view bitmaps.
- Added authenticated Ollama Cloud support, request timeouts, keep-alive, and a current multimodal default.
- Updated supported dependencies for Python 3.10 through 3.12.
- Added offline contract tests for Meshy and Tripo.
