from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FIELD_ALIAS_PATH = PACKAGE_ROOT / "config" / "field_alias.json"


def load_field_alias_config() -> dict[str, Any]:
    return json.loads(FIELD_ALIAS_PATH.read_text(encoding="utf-8"))


def normalize_name(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value)).lower()


def list_required_roles(alias_config: dict[str, Any], *, include_optional: bool = False) -> list[str]:
    roles: list[str] = []
    for role, role_config in alias_config["roles"].items():
        if include_optional or not bool(role_config.get("optional", False)):
            roles.append(role)
    return roles


def aliases_for_role_column(role: str, canonical_column: str, alias_config: dict[str, Any]) -> list[str]:
    role_config = alias_config["roles"][role]
    aliases = [canonical_column]
    aliases.extend(role_config.get("aliases", {}).get(canonical_column, []))
    return aliases


def map_frame_columns(frame: pd.DataFrame, role: str, alias_config: dict[str, Any]) -> pd.DataFrame:
    role_config = alias_config["roles"][role]
    alias_index: dict[str, str] = {}
    for canonical_column in role_config["required_columns"]:
        for alias in aliases_for_role_column(role, canonical_column, alias_config):
            alias_index[normalize_name(alias)] = canonical_column

    renamed_columns: dict[str, str] = {}
    for column in frame.columns:
        normalized = normalize_name(str(column))
        canonical = alias_index.get(normalized)
        if canonical is not None and canonical not in renamed_columns.values():
            renamed_columns[str(column)] = canonical

    mapped = frame.rename(columns=renamed_columns).copy()
    missing = [column for column in role_config["required_columns"] if column not in mapped.columns]
    if missing:
        raise KeyError(
            f"Role '{role}' is missing required columns after alias mapping: {missing}. "
            f"Available columns: {list(map(str, frame.columns))}"
        )
    return mapped
