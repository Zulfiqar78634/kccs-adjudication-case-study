"""Configuration loading with content hashes for the execution manifest."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from .sources import canonical_json, sha256_text

CONFIG_FILES = ("sop_scope_rules.json", "reference_facts.json")


@cache
def load_config(name: str) -> dict[str, Any]:
    text = resources.files("kccs_evidence.config").joinpath(name).read_text(encoding="utf-8")
    return json.loads(text)


def config_manifest() -> dict[str, dict[str, str]]:
    out = {}
    for name in CONFIG_FILES:
        cfg = load_config(name)
        out[name] = {"version": cfg.get("version", "?"), "sha256": sha256_text(canonical_json(cfg))}
    return out
