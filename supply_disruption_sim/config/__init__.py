"""Helpers for loading YAML-backed simulation configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


CONFIG_DIR = Path(__file__).resolve().parent


def load_yaml_config(file_name: str) -> dict[str, Any]:
    config_path = CONFIG_DIR / file_name
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)
