from __future__ import annotations

from pathlib import Path

from supply_disruption_sim.data_adapter.mapper import (
    list_known_roles,
    list_required_roles,
    load_field_alias_config,
    map_frame_columns,
)
from supply_disruption_sim.data_adapter.scanner import ScannedSource, load_scanned_source, scan_input_sources
from supply_disruption_sim.data_adapter.schema_detector import FILE_TYPE_PRIORITY, detect_table_role
from supply_disruption_sim.types import RawBundle


def load_raw_bundle(input_dir: str | Path) -> RawBundle:
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_path}")

    alias_config = load_field_alias_config()
    scanned_sources = scan_input_sources(input_path)
    if not scanned_sources:
        raise FileNotFoundError(f"No supported input files found under: {input_path}")

    known_roles = list_known_roles(alias_config)
    required_roles = set(list_required_roles(alias_config))
    candidates_by_role: dict[str, list[tuple[float, ScannedSource]]] = {
        role: [] for role in known_roles
    }
    for source in scanned_sources:
        detection = detect_table_role(source, alias_config)
        if detection.role is None:
            continue
        candidates_by_role[detection.role].append((detection.score, source))

    tables: dict[str, object] = {}
    missing_roles: list[str] = []
    for role in known_roles:
        candidates = sorted(
            candidates_by_role.get(role, []),
            key=lambda item: (
                item[0],
                FILE_TYPE_PRIORITY.get(item[1].file_type, 0),
                item[1].path.name,
            ),
            reverse=True,
        )
        if not candidates:
            if role in required_roles:
                missing_roles.append(role)
            continue
        best_source = candidates[0][1]
        frame = load_scanned_source(best_source)
        tables[role] = map_frame_columns(frame, role, alias_config)

    if missing_roles:
        raise FileNotFoundError(
            "Missing required logical input tables after scanning and detection: "
            f"{missing_roles}"
        )

    return RawBundle(tables=tables, source_dir=input_path)
