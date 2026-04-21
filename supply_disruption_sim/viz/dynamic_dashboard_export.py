from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from supply_disruption_sim.types import ModelBundle, SimulationResult
from supply_disruption_sim.viz.graph_export import build_export_graph


FRONTEND_POLICY_PROFILE_LABELS = {
    "time_priority_interrupt": "当前恢复策略",
    "all_policies": "全策略显示联动",
    "no_policy": "无恢复策略",
    "only_backup_switch": "仅备供切换",
    "only_substitution": "仅等效替代",
    "only_priority_repair": "仅优先抢修",
}


DYNAMIC_DASHBOARD_CONTRACT = {
    "contract_name": "study04_dynamic_frontend",
    "contract_version": "1.0.0",
    "generated_timezone": "Asia/Shanghai",
    "required_scene_fields": [
        "scene_key",
        "scene_family",
        "label",
        "accent",
        "accent_soft",
        "scenario",
        "summary",
        "kpis",
        "daily",
        "network_markers",
        "network_snapshots",
        "policy_events",
        "impacted_paths",
        "parameter_sensitivity",
        "policy_comparison_summary",
        "policy_comparison_time_series",
        "policy_profiles",
        "monthly_disrupted",
        "propagation_durations",
        "artifacts",
        "interactive_network",
    ],
    "api_endpoints": {
        "health": "/api/health",
        "contract": "/api/contract",
        "whatif_run": "/api/whatif-run",
    },
    "policy_profiles": [
        {"value": value, "label": label}
        for value, label in FRONTEND_POLICY_PROFILE_LABELS.items()
    ],
    "network_filters": [
        {"value": "process", "label": "当前过程"},
        {"value": "all", "label": "全链路"},
        {"value": "key", "label": "仅关键节点"},
        {"value": "disrupted", "label": "仅中断/阻断"},
        {"value": "supplier", "label": "仅供应商"},
        {"value": "item", "label": "仅物料/BOM"},
        {"value": "policy", "label": "仅策略作用边"},
    ],
}


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [_convert_row(row) for row in reader]


def write_dashboard_data_js(payload: dict[str, Any], output_file: Path) -> Path:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        "window.study04DynamicData = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    return output_file


def write_dashboard_contract_json(output_file: Path) -> Path:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(build_dashboard_contract(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_file


def build_scene_payload_from_frontend_dir(
    *,
    scene_key: str,
    label: str,
    accent: str,
    accent_soft: str,
    frontend_dir: Path,
    page_dir: Path,
    repo_root: Path,
    scene_family: str | None = None,
) -> dict[str, Any]:
    scenario = _to_dict(read_csv_rows(frontend_dir / "scenario.csv"))
    summary = _to_dict(read_csv_rows(frontend_dir / "summary.csv"))
    kpis = _to_dict(read_csv_rows(frontend_dir / "kpis.csv"))
    time_series = read_csv_rows(frontend_dir / "time_series.csv")
    network_time_series = read_csv_rows(frontend_dir / "network_time_series.csv")
    network_markers = read_csv_rows(frontend_dir / "network_markers.csv")
    network_snapshots = _attach_marker_metrics(
        read_csv_rows(frontend_dir / "network_snapshots.csv"),
        network_markers,
        page_dir=page_dir,
        repo_root=repo_root,
    )
    policy_events = read_csv_rows(frontend_dir / "policy_events.csv")
    impacted_paths = read_csv_rows(frontend_dir / "top_impacted_paths.csv")
    sensitivity = read_csv_rows(frontend_dir / "parameter_sensitivity_ranking.csv")
    policy_comparison_summary = _normalize_policy_profile_labels(
        read_csv_rows(frontend_dir / "policy_comparison_summary.csv")
    )
    policy_comparison_time_series = _normalize_policy_profile_labels(
        read_csv_rows(frontend_dir / "policy_comparison_time_series.csv")
    )
    artifacts = _build_artifact_map(
        read_csv_rows(frontend_dir / "artifact_paths.csv"),
        page_dir=page_dir,
        repo_root=repo_root,
    )
    daily = _build_daily_series(time_series, network_time_series)
    scenario["scene_family"] = scene_family or scene_key
    return {
        "scene_key": scene_key,
        "scene_family": scene_family or scene_key,
        "label": label,
        "accent": accent,
        "accent_soft": accent_soft,
        "scenario": scenario,
        "summary": summary,
        "kpis": kpis,
        "daily": daily,
        "network_markers": network_markers,
        "network_snapshots": network_snapshots,
        "policy_events": policy_events,
        "impacted_paths": impacted_paths,
        "parameter_sensitivity": sensitivity,
        "policy_comparison_summary": policy_comparison_summary,
        "policy_comparison_time_series": policy_comparison_time_series,
        "policy_profiles": _build_policy_profiles(policy_comparison_time_series),
        "monthly_disrupted": _build_monthly_disrupted(daily),
        "propagation_durations": _build_propagation_durations(summary),
        "artifacts": artifacts,
    }


def build_selector_graph(model: ModelBundle) -> dict[str, list[dict[str, Any]]]:
    graph, positions = build_export_graph(model)
    nodes: list[dict[str, Any]] = []
    for node_key, attrs in graph.nodes(data=True):
        x_coord, y_coord = positions[node_key]
        nodes.append(
            {
                "node_key": node_key,
                "entity_id": attrs.get("entity_id"),
                "node_type": attrs.get("node_type"),
                "item_level": attrs.get("item_level"),
                "label": attrs.get("label"),
                "short_label": attrs.get("short_label"),
                "is_key_node": bool(attrs.get("is_key_node", False)),
                "x": float(x_coord),
                "y": float(y_coord),
            }
        )

    edges: list[dict[str, Any]] = []
    for source_key, target_key, attrs in graph.edges(data=True):
        edge_type = str(attrs.get("edge_type") or "")
        if edge_type == "alternative":
            continue
        edges.append(
            {
                "edge_key": attrs.get("edge_key"),
                "edge_type": edge_type,
                "source_key": source_key,
                "target_key": target_key,
            }
        )
    return {"nodes": nodes, "edges": edges}


def build_interactive_network_payload(result: SimulationResult) -> dict[str, Any]:
    if result.model_bundle is None:
        return {}
    graph, positions = build_export_graph(result.model_bundle)
    nodes: list[dict[str, Any]] = []
    for node_key, attrs in graph.nodes(data=True):
        x_coord, y_coord = positions[node_key]
        nodes.append(
            {
                "node_key": node_key,
                "node_type": attrs.get("node_type"),
                "item_level": attrs.get("item_level"),
                "label": attrs.get("label"),
                "short_label": attrs.get("short_label"),
                "entity_id": attrs.get("entity_id"),
                "is_key_node": bool(attrs.get("is_key_node", False)),
                "x": float(x_coord),
                "y": float(y_coord),
            }
        )

    edges: list[dict[str, Any]] = []
    for source_key, target_key, attrs in graph.edges(data=True):
        edge_type = str(attrs.get("edge_type") or "")
        if edge_type == "alternative":
            continue
        edges.append(
            {
                "edge_key": attrs.get("edge_key"),
                "edge_type": edge_type,
                "source_key": source_key,
                "target_key": target_key,
            }
        )

    daily_states: list[dict[str, Any]] = []
    for snapshot in result.network_snapshots:
        node_status = {
            node_key: str((state or {}).get("visual_status") or "stable")
            for node_key, state in snapshot.get("node_state", {}).items()
        }
        edge_status = {
            edge_key: str((state or {}).get("status") or "active")
            for edge_key, state in snapshot.get("edge_state", {}).items()
        }
        daily_states.append(
            {
                "date": str(pd.Timestamp(snapshot["date"]).date()),
                "node_status": node_status,
                "edge_status": edge_status,
            }
        )
    return {"nodes": nodes, "edges": edges, "daily_states": daily_states}


def write_generated_dashboard_index(
    output_file: Path,
    *,
    title: str,
    stylesheet_href: str,
    data_script_src: str,
    app_script_src: str,
) -> Path:
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <link rel="stylesheet" href="{stylesheet_href}" />
</head>
<body>
  <div class="page-shell">
    <header class="hero">
      <h1>指定节点中断动态推演</h1>
      <p class="hero-subtitle">
        本页由节点点击触发后端实时重算自动生成，保留基准情境并追加指定节点定点中断结果，
        用于查看从中断开始、恢复动作启动到业务恢复的全过程动态传播。
      </p>
    </header>

    <main class="content">
      <section class="panel scenario-panel">
        <div class="section-head">
          <div>
            <h2>场景切换与总览对照</h2>
          </div>
          <div class="scene-pill-group" id="scene-pill-group"></div>
        </div>
        <div class="scene-card-grid" id="scene-card-grid"></div>
        <div class="compare-grid" id="compare-grid"></div>
      </section>

      <section class="control-row">
        <div class="panel control-panel">
          <div class="section-head compact">
            <div>
              <h2>时间联动控制</h2>
            </div>
            <button class="ghost-button" id="play-toggle" type="button">播放时间轴</button>
          </div>
          <div class="timeline-controller">
            <input id="date-slider" type="range" min="0" max="0" step="1" value="0" />
            <div class="timeline-meta">
              <div>
                <span class="meta-label">当前日期</span>
                <strong id="selected-date-text">-</strong>
              </div>
              <div>
                <span class="meta-label">当前阶段</span>
                <strong id="selected-stage-text">-</strong>
              </div>
              <div>
                <span class="meta-label">说明</span>
                <strong id="selected-stage-caption">-</strong>
              </div>
            </div>
          </div>
        </div>

        <aside class="panel detail-panel" id="detail-panel"></aside>
      </section>

      <section class="trend-grid" id="trend-grid"></section>

      <section class="panel selector-panel" id="selector-panel">
        <div class="section-head">
          <div>
            <h2>节点中断推演器</h2>
          </div>
          <div class="scene-pill-group" id="api-status-group"></div>
        </div>
        <div class="selector-layout">
          <div class="selector-visual" id="selector-visual"></div>
          <div class="selector-copy" id="selector-copy"></div>
        </div>
      </section>

      <section class="panel network-panel">
        <div class="section-head">
          <div>
            <h2>阶段网络演进播放器</h2>
          </div>
          <div class="stage-chips" id="stage-chip-list"></div>
        </div>
        <div class="network-layout">
          <div class="network-visual" id="network-visual">
            <img id="network-stage-image" alt="网络阶段快照" />
          </div>
          <div class="network-copy" id="network-copy"></div>
        </div>
      </section>

      <section class="analysis-grid">
        <div class="panel" id="policy-comparison-panel"></div>
        <div class="panel" id="sensitivity-panel"></div>
        <div class="panel" id="monthly-panel"></div>
        <div class="panel" id="duration-panel"></div>
      </section>

      <section class="panel" id="paths-panel"></section>
      <section class="panel" id="events-panel"></section>
    </main>
  </div>

  <script src="{data_script_src}"></script>
  <script src="{app_script_src}"></script>
</body>
</html>
"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")
    return output_file


def _build_daily_series(
    time_series_rows: list[dict[str, Any]],
    network_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in time_series_rows:
        merged[str(row["date"])] = dict(row)
    for row in network_rows:
        merged.setdefault(str(row["date"]), {"date": row["date"]}).update(row)
    return sorted(merged.values(), key=lambda item: str(item["date"]))


def _build_monthly_disrupted(daily_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in daily_rows:
        date_text = str(row["date"])
        month_key = date_text[:7]
        grouped.setdefault(
            month_key,
            {
                "month": month_key,
                "supplier_disrupted_nodes": 0,
                "material_disrupted_nodes": 0,
                "assembly_disrupted_nodes": 0,
                "product_disrupted_nodes": 0,
                "total_disrupted_nodes": 0,
            },
        )
        supplier_value = int(row.get("supplier_disrupted_nodes") or 0)
        material_value = int(row.get("material_blocked_nodes") or 0)
        assembly_value = int(row.get("assembly_blocked_nodes") or 0)
        product_value = int(row.get("product_blocked_nodes") or 0)
        total_value = supplier_value + material_value + assembly_value + product_value
        bucket = grouped[month_key]
        bucket["supplier_disrupted_nodes"] = max(bucket["supplier_disrupted_nodes"], supplier_value)
        bucket["material_disrupted_nodes"] = max(bucket["material_disrupted_nodes"], material_value)
        bucket["assembly_disrupted_nodes"] = max(bucket["assembly_disrupted_nodes"], assembly_value)
        bucket["product_disrupted_nodes"] = max(bucket["product_disrupted_nodes"], product_value)
        bucket["total_disrupted_nodes"] = max(bucket["total_disrupted_nodes"], total_value)
    return [grouped[key] for key in sorted(grouped)]


def _build_propagation_durations(summary_row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "layer": "overall",
            "label": "整体传播",
            "duration_months": int(summary_row.get("propagation_duration_months") or 0),
        },
        {
            "layer": "supplier",
            "label": "供应商层",
            "duration_months": int(summary_row.get("supplier_propagation_duration_months") or 0),
        },
        {
            "layer": "material",
            "label": "物料层",
            "duration_months": int(summary_row.get("material_propagation_duration_months") or 0),
        },
        {
            "layer": "assembly",
            "label": "装配层",
            "duration_months": int(summary_row.get("assembly_propagation_duration_months") or 0),
        },
        {
            "layer": "product",
            "label": "产品层",
            "duration_months": int(summary_row.get("product_propagation_duration_months") or 0),
        },
    ]


def _build_policy_profiles(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        profile = str(row.get("policy_profile") or "")
        grouped[profile] = {
            "policy_profile": profile,
            "policy_label": _frontend_policy_profile_label(profile, row.get("policy_label") or profile),
        }
    preferred_order = [
        "time_priority_interrupt",
        "all_policies",
        "no_policy",
        "only_backup_switch",
        "only_substitution",
        "only_priority_repair",
    ]
    ordered = [grouped[key] for key in preferred_order if key in grouped]
    for key in grouped:
        if key not in preferred_order:
            ordered.append(grouped[key])
    return ordered


def _normalize_policy_profile_labels(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        normalized = dict(row)
        profile = str(normalized.get("policy_profile") or "")
        if profile:
            normalized["policy_label"] = _frontend_policy_profile_label(
                profile,
                normalized.get("policy_label") or profile,
            )
        normalized_rows.append(normalized)
    return normalized_rows


def _frontend_policy_profile_label(profile: str, fallback: Any = None) -> str:
    normalized = str(profile or "").strip()
    return FRONTEND_POLICY_PROFILE_LABELS.get(normalized, str(fallback or normalized or "未命名策略"))


def _attach_marker_metrics(
    snapshots: list[dict[str, Any]],
    markers: list[dict[str, Any]],
    *,
    page_dir: Path,
    repo_root: Path,
) -> list[dict[str, Any]]:
    marker_map = {str(row.get("marker_name")): row for row in markers}
    enriched: list[dict[str, Any]] = []
    for row in snapshots:
        snapshot_name = str(row.get("snapshot_name") or "")
        marker = marker_map.get(snapshot_name, {})
        item = dict(row)
        item["figure_path"] = _normalize_asset_path(row.get("figure_path"), page_dir=page_dir, repo_root=repo_root)
        item["supplier_disrupted_nodes"] = int(marker.get("supplier_disrupted_nodes") or 0)
        item["material_affected_nodes"] = int(marker.get("material_affected_nodes") or 0)
        item["bom_edge_disrupted"] = int(marker.get("bom_edge_disrupted") or 0)
        enriched.append(item)
    return enriched


def _build_artifact_map(
    rows: list[dict[str, Any]],
    *,
    page_dir: Path,
    repo_root: Path,
) -> dict[str, str]:
    return {
        str(row["artifact_name"]): _normalize_asset_path(row.get("artifact_path"), page_dir=page_dir, repo_root=repo_root)
        for row in rows
        if row.get("artifact_name") and row.get("artifact_path")
    }


def _normalize_asset_path(raw_value: str | None, *, page_dir: Path, repo_root: Path) -> str | None:
    if not raw_value:
        return None
    text = str(raw_value).replace("\\", "/")
    path = Path(text)
    if path.is_absolute():
        absolute_path = path
    elif text.startswith("output/"):
        absolute_path = repo_root / text
    else:
        absolute_path = (repo_root / text).resolve()
    try:
        relative = absolute_path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return text
    target = (repo_root / relative).resolve()
    return os.path.relpath(target, start=page_dir.resolve()).replace("\\", "/")


def _convert_row(row: dict[str, str]) -> dict[str, Any]:
    return {key: _parse_value(value) for key, value in row.items()}


def _parse_value(value: str | None) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if _looks_like_int(text):
        try:
            return int(text)
        except ValueError:
            return text
    if _looks_like_float(text):
        try:
            return float(text)
        except ValueError:
            return text
    return text


def _looks_like_int(text: str) -> bool:
    if text.startswith("-"):
        return text[1:].isdigit()
    return text.isdigit()


def _looks_like_float(text: str) -> bool:
    if text.count(".") != 1:
        return False
    left, right = text.split(".", 1)
    if left.startswith("-"):
        left = left[1:]
    return left.isdigit() and right.isdigit()


def _to_dict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return rows[0] if rows else {}


def build_dashboard_payload(
    *,
    scenes: dict[str, dict[str, Any]],
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "contract": build_dashboard_contract(),
        "meta": meta or {},
        "scenes": scenes,
    }


def build_dashboard_contract() -> dict[str, Any]:
    return json.loads(json.dumps(DYNAMIC_DASHBOARD_CONTRACT, ensure_ascii=False))
