"""Content-addressed cache for LLM responses."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from manuallabor.contracts.io import canonical_json, dump_json

log = logging.getLogger(__name__)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LLMCache:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @staticmethod
    def key(namespace: str, task: str, kind: str, inputs: Mapping[str, Any]) -> str:
        payload = {
            "namespace": namespace,
            "task": str(task),
            "kind": str(kind),
            "inputs": inputs,
        }
        return sha256_hex(canonical_json(payload))

    def path_for(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        p = self.path_for(key)
        try:
            raw = p.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            log.warning("llm cache: cannot read %s: %s", p, exc)
            return None
        try:
            entry = json.loads(raw)
        except ValueError:
            log.warning("llm cache: unparsable entry %s treated as miss", p)
            return None
        if not isinstance(entry, dict) or entry.get("key") != key:
            log.warning("llm cache: key mismatch in %s treated as miss", p)
            return None
        response = entry.get("response")
        if not isinstance(response, dict) or not any(k in response for k in ("text", "vectors")):
            log.warning("llm cache: entry %s lacks a response, treated as miss", p)
            return None
        return entry

    def put(self, key: str, entry: Mapping[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.path_for(key)
        tmp = p.with_name(p.name + ".tmp")
        data = {**entry, "key": key}
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(dump_json(data))
        os.replace(tmp, p)
