"""Canned figure-description reply for the mock vision provider (stdlib only, so that
providers/mock.py can import it without import cycles)."""

from __future__ import annotations

import hashlib
import json


def mock_describe_reply(image_bytes: bytes, prompt: str) -> str:
    """A schema-valid describe reply that depends only on the image bytes."""
    sha8 = hashlib.sha256(image_bytes).hexdigest()[:8]
    reply = {
        "description": f"Generated description (mock) of image {sha8}.",
        "tags": ["figure", "mock"],
    }
    return json.dumps(reply, sort_keys=True)
