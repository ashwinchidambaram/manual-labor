"""Hatch build hook: ship the built UI (frontend/dist) inside the wheel as manuallabor/_frontend.

`manuallabor.serve.find_frontend_dist` looks there second, so a `uv tool install` or `pipx install`
of the wheel serves the UI with no Node toolchain. Build the UI first (`npm ci && npm run build`
in frontend/), then `uv build --wheel`. Set MANUALLABOR_REQUIRE_UI=1 to fail instead of building a
UI-less wheel. Editable installs (`uv sync`) skip this; they use frontend/dist from the checkout.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class FrontendBuildHook(BuildHookInterface):  # type: ignore[misc]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if version != "standard":
            return
        dist = Path(self.root) / "frontend" / "dist"
        if (dist / "index.html").is_file():
            build_data["force_include"][str(dist)] = "manuallabor/_frontend"
            return
        msg = f"frontend/dist/index.html not found: this wheel will have no UI ({dist})"
        if os.environ.get("MANUALLABOR_REQUIRE_UI") == "1":
            raise RuntimeError(msg + "; run `npm ci && npm run build` in frontend/ first")
        print(f"warning: {msg}", file=sys.stderr)
