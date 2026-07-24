# Changelog

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
