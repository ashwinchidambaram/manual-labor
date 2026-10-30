"""Model candidates per task and tier. Pure data: a wrong tag is a one-line fix here."""

from __future__ import annotations

from typing import NamedTuple


class Candidate(NamedTuple):
    provider: str
    model: str
    approx_gb: float


# The agent is a tier task too: the small chat model cannot follow the proposal schema, so the
# agent gets the smallest model that can (measured in tests/agent/test_live.py).
TASKS = ("cleanup", "grouping", "vision", "verifier", "embeddings", "agent")
# Tasks that run inside one pipeline job and are resident together; the agent runs in its own
# job afterwards, with vision (page images) and embeddings (regroup similarity) at most.
PIPELINE_TASKS = ("cleanup", "grouping", "vision", "verifier", "embeddings")
AGENT_TASKS = ("agent", "vision", "embeddings")
TIERS = ("small", "medium", "large")

_CHAT_S = Candidate("ollama", "llama3.2:1b", 1.3)
_CHAT_M = Candidate("ollama", "qwen2.5:7b", 4.7)
_CHAT_L = Candidate("ollama", "qwen2.5:14b", 9.0)
# The verifier must never be the cleanup model (TaskModels enforces it): small -> a model of
# another family/size, medium/large -> a different model than the cleanup one in the same tier.
_VERIFIER_S = Candidate("ollama", "qwen2.5:1.5b", 1.0)
# Smallest local model that follows the agent proposal schema (qwen2.5:1.5b and llama3.2:1b do
# not; 2026-10-30 trial on tests/agent/test_live.py test 31b).
_AGENT_S = Candidate("ollama", "qwen2.5:3b", 1.9)

CATALOG: dict[str, dict[str, Candidate]] = {
    "cleanup": {"small": _CHAT_S, "medium": _CHAT_M, "large": _CHAT_L},
    "grouping": {"small": _CHAT_S, "medium": _CHAT_M, "large": _CHAT_L},
    "verifier": {
        "small": _VERIFIER_S,
        "medium": Candidate("ollama", "llama3.2:3b", 2.0),
        "large": _CHAT_M,
    },
    "vision": {
        "small": Candidate("ollama", "moondream", 1.7),
        "medium": Candidate("ollama", "gemma3:4b", 3.3),
        "large": Candidate("ollama", "llama3.2-vision:11b", 7.8),
    },
    "embeddings": {
        "small": Candidate("ollama", "nomic-embed-text", 0.27),
        "medium": Candidate("ollama", "mxbai-embed-large", 0.67),
        "large": Candidate("ollama", "bge-m3", 1.2),
    },
    "agent": {"small": _AGENT_S, "medium": _CHAT_M, "large": _CHAT_L},
}

_API_CHAT = Candidate("anthropic", "claude-haiku-4-5", 0.0)
_API_VERIFIER = Candidate("anthropic", "claude-sonnet-4-5", 0.0)
API: dict[str, Candidate] = {
    "cleanup": _API_CHAT,
    "grouping": _API_CHAT,
    "verifier": _API_VERIFIER,
    "vision": _API_CHAT,
    # Anthropic has no embeddings API.
    "embeddings": Candidate("openai", "text-embedding-3-small", 0.0),
    "agent": _API_CHAT,
}
API_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
