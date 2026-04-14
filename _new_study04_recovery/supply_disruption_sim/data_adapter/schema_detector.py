from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from supply_disruption_sim.data_adapter.mapper import aliases_for_role_column, normalize_name
from supply_disruption_sim.data_adapter.scanner import ScannedSource


FILE_TYPE_PRIORITY = {"csv": 3, "excel": 2, "json": 1}


@dataclass(slots=True)
class RoleDetection:
    role: str | None
    score: float
    scores: dict[str, float]


def detect_table_role(source: ScannedSource, alias_config: dict[str, Any]) -> RoleDetection:
    normalized_table_name = normalize_name(source.table_name)
    normalized_columns = {normalize_name(column) for column in source.columns}
    scores: dict[str, float] = {}

    for role, role_config in alias_config["roles"].items():
        score = 0.0
        file_aliases = [normalize_name(alias) for alias in role_config.get("file_aliases", [])]
        if normalized_table_name in file_aliases:
            score += 30.0
        elif any(alias and alias in normalized_table_name for alias in file_aliases):
            score += 12.0

        required_columns = role_config["required_columns"]
        matched_columns = 0
        for canonical_column in required_columns:
            normalized_aliases = {
                normalize_name(alias) for alias in aliases_for_role_column(role, canonical_column, alias_config)
            }
            if normalized_columns & normalized_aliases:
                matched_columns += 1

        if required_columns:
            coverage = matched_columns / len(required_columns)
            score += coverage * 40.0
            score += matched_columns

        scores[role] = round(score, 4)

    best_role, best_score = max(scores.items(), key=lambda item: item[1], default=(None, 0.0))
    if best_role is None or best_score <= 0:
        return RoleDetection(role=None, score=0.0, scores=scores)
    return RoleDetection(role=best_role, score=best_score, scores=scores)
