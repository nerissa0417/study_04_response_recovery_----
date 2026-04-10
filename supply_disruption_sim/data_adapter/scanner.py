from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd


SUPPORTED_SUFFIXES = {".csv", ".json", ".xlsx", ".xls"}


@dataclass(slots=True)
class ScannedSource:
    path: Path
    file_type: str
    table_name: str
    sheet_name: str | None
    columns: list[str]
    row_count: int
    column_count: int


def scan_input_sources(input_dir: str | Path) -> list[ScannedSource]:
    input_path = Path(input_dir)
    scanned: list[ScannedSource] = []
    for path in sorted(input_path.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        scanned.extend(_scan_path(path))
    return scanned


def load_scanned_source(source: ScannedSource) -> pd.DataFrame:
    if source.file_type == "csv":
        return pd.read_csv(source.path)
    if source.file_type == "json":
        payload = json.loads(source.path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return pd.DataFrame(payload)
        if isinstance(payload, dict):
            for candidate_key in ["data", "records", "items", "rows"]:
                if isinstance(payload.get(candidate_key), list):
                    return pd.DataFrame(payload[candidate_key])
            return pd.DataFrame(payload)
    if source.file_type == "excel":
        return pd.read_excel(source.path, sheet_name=source.sheet_name)
    raise ValueError(f"Unsupported scanned source type: {source.file_type}")


def _scan_path(path: Path) -> list[ScannedSource]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(path, nrows=20)
        return [_build_source(path=path, file_type="csv", frame=frame)]
    if suffix == ".json":
        frame = load_scanned_source(
            ScannedSource(
                path=path,
                file_type="json",
                table_name=path.stem,
                sheet_name=None,
                columns=[],
                row_count=0,
                column_count=0,
            )
        )
        preview = frame.head(20)
        return [_build_source(path=path, file_type="json", frame=preview)]
    if suffix in {".xlsx", ".xls"}:
        sources: list[ScannedSource] = []
        with pd.ExcelFile(path) as workbook:
            for sheet_name in workbook.sheet_names:
                frame = workbook.parse(sheet_name=sheet_name, nrows=20)
                sources.append(_build_source(path=path, file_type="excel", frame=frame, sheet_name=sheet_name))
        return sources
    return []


def _build_source(
    *,
    path: Path,
    file_type: str,
    frame: pd.DataFrame,
    sheet_name: str | None = None,
) -> ScannedSource:
    table_name = path.stem if sheet_name is None else f"{path.stem}#{sheet_name}"
    return ScannedSource(
        path=path,
        file_type=file_type,
        table_name=table_name,
        sheet_name=sheet_name,
        columns=[str(column) for column in frame.columns],
        row_count=int(len(frame)),
        column_count=int(len(frame.columns)),
    )
