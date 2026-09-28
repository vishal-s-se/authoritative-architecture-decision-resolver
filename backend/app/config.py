"""
Central configuration for the authority scoring model.
All weights/levels are runtime-mutable through the /api/settings endpoints
and are persisted to config.json so changes survive restarts.
"""
import json
import os
import threading

CONFIG_PATH = os.environ.get(
    "ADR_CONFIG_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "data", "config.json")
)
CONFIG_PATH = os.path.abspath(CONFIG_PATH)

DEFAULT_CONFIG = {
    "weights": {
        "approval": 0.40,
        "ownership": 0.25,
        "recency": 0.20,
        "version": 0.10,
        "evidence": 0.05,
    },
    "status_scores": {
        "APPROVED": 1.0,
        "PENDING_REVIEW": 0.4,
        "DRAFT": 0.2,
        "SUPERSEDED": 0.1,
        "ARCHIVED": 0.05,
        "REJECTED": 0.0,
    },
    "recency_half_life_days": 180,
    "ai_provider": os.environ.get("ADR_AI_PROVIDER", "mock"),
    "ai_model": os.environ.get("ADR_AI_MODEL", "mock-llm"),
}

_lock = threading.Lock()


def load_config():
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_PATH, "r") as f:
        cfg = json.load(f)
    # backfill any missing keys with defaults
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    merged.update(cfg)
    if "weights" in cfg:
        merged["weights"] = {**DEFAULT_CONFIG["weights"], **cfg["weights"]}
    return merged


def save_config(cfg):
    with _lock:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
