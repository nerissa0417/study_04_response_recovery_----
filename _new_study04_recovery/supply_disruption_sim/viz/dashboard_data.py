from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from supply_disruption_sim.types import SimulationResult
from supply_disruption_sim.viz.network_trend_plot import build_network_markers


def export_dashboard_data(
    result: SimulationResult,
    output_path: str | Path,
    *,
    artifact_paths: dict[str, str] | None = None,
    network_history: pd.DataFrame | None = None,
    params: dict[str, Any] | None = None,
    display_spec_path: str | Path | None = None,
) -> Path:
    payload = build_dashboard_payload(
        result=result,
        artifact_paths=artifact_paths or {},
        network_history=network_history,
        params=params,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    display_spec_destination = Path(display_spec_path) if display_spec_path is not None else destination.parent / "display_spec.md"
    payload.setdefault("artifact_paths", {})["display_spec_markdown"] = str(display_spec_destination)
    _export_dashboard_csvs(payload, destination.parent / "tables")
    _export_display_spec_markdown(payload, display_spec_destination)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return destination


def build_dashboard_payload(
    *,
    result: SimulationResult,
    artifact_paths: dict[str, str],
    network_history: pd.DataFrame | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    history = result.history.copy()
    history["date"] = pd.to_datetime(history["date"])
    network_frame = (
        network_history.copy()
        if network_history is not None
        else pd.DataFrame(columns=["date"])
    )
    if not network_frame.empty:
        network_frame["date"] = pd.to_datetime(network_frame["date"])
    kpis = {
        "scenario_id": result.scenario.scenario_id,
        "target_id": result.summary.get("target_id"),
        "ttr_days": result.summary.get("ttr_days"),
        "propagation_duration_months": result.summary.get("propagation_duration_months"),
        "propagation_stop_date": result.summary.get("propagation_stop_date"),
        "average_service_level": result.summary.get("average_service_level"),
        "avg_system_service_level": result.summary.get("avg_system_service_level"),
        "estimated_disruption_loss": result.summary.get("estimated_disruption_loss"),
        "policy_total_cost": result.summary.get("policy_total_cost"),
        "max_affected_key_items": result.summary.get("max_affected_key_items"),
        "max_failed_key_items": result.summary.get("max_failed_key_items"),
        "max_disrupted_key_suppliers": result.summary.get("max_disrupted_key_suppliers"),
    }
    peak_row = _select_peak_row(history)
    return {
        "scenario": {
            "scenario_id": result.scenario.scenario_id,
            "scenario_type": result.scenario.scenario_type,
            "target_type": result.scenario.target_type,
            "target_id": result.scenario.target_id,
            "start_date": str(result.scenario.start_date.date()),
            "duration_days": result.scenario.duration_days,
            "severity": result.scenario.severity,
        },
        "runtime": _build_runtime_metadata(params),
        "summary": result.summary,
        "kpis": kpis,
        "peak_snapshot": {
            "date": str(peak_row["date"].date()) if peak_row is not None else None,
            "service_level": float(peak_row["service_level"]) if peak_row is not None and "service_level" in peak_row else None,
            "fused_failed_items": int(peak_row["fused_failed_items"]) if peak_row is not None and "fused_failed_items" in peak_row else None,
            "total_backlog_demand": float(peak_row["total_backlog_demand"]) if peak_row is not None and "total_backlog_demand" in peak_row else None,
        },
        "time_series": _build_time_series(history),
        "network_time_series": _build_network_time_series(network_frame),
        "network_markers": build_network_markers(result, network_frame),
        "top_impacted_paths": result.impacted_paths[:12],
        "policy_events": result.policy_events,
        "artifact_paths": artifact_paths,
    }


def _build_time_series(history: pd.DataFrame) -> list[dict[str, Any]]:
    columns = [
        "date",
        "service_level",
        "demand_fulfillment_rate",
        "system_service_level",
        "supply_unavailable_items",
        "total_backlog_demand",
        "fused_failed_items",
        "affected_key_items",
        "failed_key_items",
        "disrupted_key_suppliers",
        "policy_cumulative_cost",
        "active_backup_switches",
        "active_priority_repairs",
    ]
    available = [column for column in columns if column in history.columns]
    records = history[available].copy().to_dict("records")
    for record in records:
        if "date" in record:
            record["date"] = str(pd.Timestamp(record["date"]).date())
    return records


def _export_dashboard_csvs(payload: dict[str, Any], tables_dir: Path) -> dict[str, Path]:
    tables_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = payload.setdefault("artifact_paths", {})
    datasets: dict[str, tuple[list[dict[str, Any]], list[str], str]] = {
        "dashboard_scenario": (
            _records_from_mapping(payload.get("scenario")),
            ["scenario_id", "scenario_type", "target_type", "target_id", "start_date", "duration_days", "severity"],
            "Scenario metadata shown by the dashboard header.",
        ),
        "dashboard_runtime": (
            _records_from_mapping(payload.get("runtime")),
            ["mode", "bayesian_enabled", "bayesian_use_sampling", "bayesian_random_seed"],
            "Runtime mode metadata used to explain deterministic vs. Bayesian interpretation.",
        ),
        "dashboard_summary": (
            _records_from_mapping(payload.get("summary")),
            [],
            "One-row summary metrics used by dashboard panels.",
        ),
        "dashboard_kpis": (
            _records_from_mapping(payload.get("kpis")),
            [],
            "KPI cards shown at the top of the dashboard.",
        ),
        "dashboard_peak_snapshot": (
            _records_from_mapping(payload.get("peak_snapshot")),
            ["date", "service_level", "fused_failed_items", "total_backlog_demand"],
            "Worst-impact snapshot highlighted by the dashboard.",
        ),
        "dashboard_time_series": (
            _records_from_sequence(payload.get("time_series")),
            ["date"],
            "Core monthly time-series used by service, demand, and policy trend charts.",
        ),
        "dashboard_network_time_series": (
            _records_from_sequence(payload.get("network_time_series")),
            ["date"],
            "Supplier, material, BOM, and supply-edge network trend data.",
        ),
        "dashboard_network_markers": (
            _records_from_marker_mapping(payload.get("network_markers")),
            ["marker_id", "date", "label", "value"],
            "Important timeline markers used as annotations on network charts.",
        ),
        "dashboard_top_impacted_paths": (
            _records_from_sequence(payload.get("top_impacted_paths"), rank_column="path_rank"),
            ["path_rank"],
            "Top BOM impact paths displayed in the path-impact view.",
        ),
        "dashboard_policy_events": (
            _records_from_sequence(payload.get("policy_events"), rank_column="event_rank"),
            ["event_rank"],
            "Policy events displayed in the event timeline/table.",
        ),
    }

    csv_paths: dict[str, Path] = {}
    index_rows: list[dict[str, Any]] = []
    for dataset_name, (records, fallback_columns, description) in datasets.items():
        path = tables_dir / f"{dataset_name}.csv"
        row_count = _write_dashboard_csv(path, records, fallback_columns)
        csv_paths[dataset_name] = path
        index_rows.append(
            {
                "dataset_name": dataset_name,
                "csv_path": str(path),
                "row_count": row_count,
                "description": description,
            }
        )

    artifact_paths.update({f"{dataset_name}_csv": str(path) for dataset_name, path in csv_paths.items()})
    artifact_paths_path = tables_dir / "dashboard_artifact_paths.csv"
    csv_paths["dashboard_artifact_paths"] = artifact_paths_path
    artifact_paths["dashboard_artifact_paths_csv"] = str(artifact_paths_path)
    index_path = tables_dir / "dashboard_csv_index.csv"
    csv_paths["dashboard_csv_index"] = index_path
    artifact_paths["dashboard_csv_index_csv"] = str(index_path)

    artifact_row_count = _write_dashboard_csv(
        artifact_paths_path,
        _records_from_artifact_paths(artifact_paths),
        ["artifact_key", "artifact_value", "item_index"],
    )
    index_rows.append(
        {
            "dataset_name": "dashboard_artifact_paths",
            "csv_path": str(artifact_paths_path),
            "row_count": artifact_row_count,
            "description": "Dashboard-linked files and figures.",
        }
    )
    index_rows.append(
        {
            "dataset_name": "dashboard_csv_index",
            "csv_path": str(index_path),
            "row_count": len(index_rows) + 1,
            "description": "Index of dashboard CSV exports and their display roles.",
        }
    )
    pd.DataFrame(index_rows).to_csv(index_path, index=False)
    return csv_paths


def _write_dashboard_csv(path: Path, records: list[dict[str, Any]], fallback_columns: list[str]) -> int:
    frame = pd.DataFrame(records)
    if frame.empty and fallback_columns:
        frame = pd.DataFrame(columns=fallback_columns)
    if not frame.empty:
        frame = frame.apply(lambda column: column.map(_serialise_csv_value))
    frame.to_csv(path, index=False)
    return int(len(frame))


def _export_display_spec_markdown(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_build_display_spec_markdown(payload), encoding="utf-8")
    return path


def _build_display_spec_markdown(payload: dict[str, Any]) -> str:
    scenario = payload.get("scenario") if isinstance(payload.get("scenario"), dict) else {}
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    artifacts = payload.get("artifact_paths") if isinstance(payload.get("artifact_paths"), dict) else {}
    csv_index_path = artifacts.get("dashboard_csv_index_csv", "")

    mode = str(runtime.get("mode") or "unknown")
    bayesian_enabled = bool(runtime.get("bayesian_enabled", mode == "bayesian"))
    bayesian_logic = (
        "贝叶斯模式只用于中断传播概率：先在供应商上下游网络判断中断/降级是否扩散，再在供应商-物料供应边判断是否传递到物料。"
        "恢复策略、需求积压、需求损失比例和最终产品中断判定仍由主仿真链路计算。"
        if bayesian_enabled
        else "当前为默认确定性模式，不启用供应商网络贝叶斯概率传播；供应商/供应边状态直接进入主传播链。"
    )

    lines = [
        "# 展示数据与可视化逻辑说明",
        "",
        "本文档由报告生成流程自动创建，用于说明本次仿真输出中各类 CSV、图表和网络快照的期望展现形式与解释逻辑。",
        "",
        "## 本次运行概览",
        "",
        "| 项目 | 值 |",
        "| --- | --- |",
        f"| scenario_id | {_md(scenario.get('scenario_id'))} |",
        f"| scenario_type | {_md(scenario.get('scenario_type'))} |",
        f"| target_type | {_md(scenario.get('target_type'))} |",
        f"| target_id | {_md(scenario.get('target_id'))} |",
        f"| start_date | {_md(scenario.get('start_date'))} |",
        f"| duration_days | {_md(scenario.get('duration_days'))} |",
        f"| mode | {_md(mode)} |",
        f"| bayesian_enabled | {_md(runtime.get('bayesian_enabled'))} |",
        f"| ttr_days | {_md(summary.get('ttr_days'))} |",
        f"| propagation_duration_months | {_md(summary.get('propagation_duration_months'))} |",
        f"| average_service_level | {_md(summary.get('average_service_level'))} |",
        "",
        "## 主传播逻辑",
        "",
        "主链路保持为：供应商状态/供应边状态 -> 物料供给状态 -> BOM 子件向装配和终品传播 -> 需求履约与供需融合。",
        "",
        bayesian_logic,
        "",
        "BOM 不直接用贝叶斯判定终品是否中断；终品状态来自物料供给、BOM 依赖、需求履约和融合规则共同计算。",
        "",
        "## 展示页面与数据来源",
        "",
        "| 展示内容 | 主要数据源 | 期望展现形式 | 解释逻辑 |",
        "| --- | --- | --- | --- |",
        f"| KPI 卡片 | {_artifact_link(artifacts, 'dashboard_kpis_csv')} | 展示 TTR、传播月数、平均服务水平、损失和策略成本等核心指标。 | 作为结果摘要，不参与二次计算。 |",
        f"| 核心趋势图 | {_artifact_link(artifacts, 'dashboard_time_series_csv')} | 折线展示服务水平、需求满足率、系统服务水平、受影响/失败节点和策略动作。 | 横轴为日期，纵轴按指标含义分面展示。 |",
        f"| 网络趋势图 | {_artifact_link(artifacts, 'dashboard_network_time_series_csv')} | 分供应商、物料、BOM、供应边等维度展示节点和边状态变化。 | 使用 t0、t_start、t_peak、t_recovery 标记关键时点。 |",
        f"| 网络快照图 | {_artifact_link(artifacts, 'network_snapshot_paths')} | 展示 t0、冲击开始、峰值、恢复四类网络状态快照。 | 节点颜色表示状态，节点形状表示类型，边线样式表示供应/备用/中断关系。 |",
        f"| BOM 影响路径图 | {_artifact_link(artifacts, 'bom_figure')} | BOM 层级从左到右排列，边为直线箭头，装配列纵向拉开，节点和标签适当缩小。 | 只展示优先级最高的影响路径，按影响维度着色。 |",
        f"| 路径表 | {_artifact_link(artifacts, 'dashboard_top_impacted_paths_csv')} | 表格列出 Top BOM 影响路径、影响维度和状态。 | 与 BOM 图使用同一批优先路径。 |",
        f"| 策略事件表 | {_artifact_link(artifacts, 'dashboard_policy_events_csv')} | 表格或时间线展示备用供应商切换、替代料、优先维修等事件。 | 事件来自恢复策略调度和激活记录，不由贝叶斯直接生成。 |",
        f"| 关键/非关键节点表 | {_artifact_link(artifacts, 'key_node_states_csv')} / {_artifact_link(artifacts, 'general_node_states_csv')} | 关键节点和普通节点分表展示。 | 当前关键节点来自输入字段或临时关键节点选择逻辑，终品不参与随机关键节点选择。 |",
        "",
        "## 视觉编码规则",
        "",
        "| 对象 | 编码 | 含义 |",
        "| --- | --- | --- |",
        "| 节点颜色 | 绿色/青色为可用，橙色为降级或受影响，红色为中断或阻断，蓝色为恢复中，灰色为稳定/未受影响。 | 用于快速判断状态严重程度。 |",
        "| 节点形状 | 圆形为供应商，方形为物料/零件，菱形为装配件，三角形为终品。 | 用于区分供应网络、物料网络和 BOM 层级。 |",
        "| 关键节点 | 金色描边并加星标。 | 用于突出关键物料或关键供应商。 |",
        "| BOM 边 | 直线箭头，不弯折；颜色区分融合影响、供应影响、需求影响。 | 箭头方向表示从子件向装配/终品传播。 |",
        "| 网络边 | 实线为正常/激活关系，较深较粗虚线为备用/待命边，点线为中断边，点划线为替代边。 | 用于区分真实供给、备用供给和异常边。 |",
        "",
        "## Dashboard CSV 清单",
        "",
        f"CSV 索引表：{_md(csv_index_path)}",
        "",
        "| CSV | 作用 |",
        "| --- | --- |",
        f"| dashboard_scenario.csv | 场景元数据，用于标题和场景信息区。 |",
        f"| dashboard_runtime.csv | 运行模式信息，用于解释确定性/贝叶斯逻辑。 |",
        f"| dashboard_summary.csv | 一行 summary 指标，用于报告摘要。 |",
        f"| dashboard_kpis.csv | KPI 卡片数据。 |",
        f"| dashboard_peak_snapshot.csv | 峰值影响快照。 |",
        f"| dashboard_time_series.csv | 核心指标趋势。 |",
        f"| dashboard_network_time_series.csv | 网络节点/边状态趋势。 |",
        f"| dashboard_network_markers.csv | t0、t_start、t_peak、t_recovery 标注点。 |",
        f"| dashboard_top_impacted_paths.csv | Top BOM 影响路径。 |",
        f"| dashboard_policy_events.csv | 策略事件。 |",
        f"| dashboard_artifact_paths.csv | 所有输出文件、图表和 CSV 的路径清单。 |",
        "",
        "## 读取顺序建议",
        "",
        "1. 先看 summary.csv 和 dashboard_kpis.csv，确认本次运行的核心指标。",
        "2. 再看 dashboard_time_series.csv 和 dashboard_network_time_series.csv，判断传播过程和恢复过程。",
        "3. 然后结合 BOM 影响路径图、网络快照图和对应 CSV，解释具体是哪些供应商、物料和 BOM 路径造成影响。",
        "4. 最后用 policy_events.csv 和 dashboard_policy_events.csv 解释恢复策略何时被调度或激活。",
        "",
    ]
    return "\n".join(lines)


def _build_runtime_metadata(params: dict[str, Any] | None) -> dict[str, Any]:
    params = dict(params or {})
    mode = str(params.get("mode", "unknown"))
    return {
        "mode": mode,
        "bayesian_enabled": params.get("bayesian_enabled", mode == "bayesian"),
        "bayesian_use_sampling": params.get("bayesian_use_sampling"),
        "bayesian_random_seed": params.get("bayesian_random_seed"),
    }


def _artifact_link(artifacts: dict[str, Any], key: str) -> str:
    value = artifacts.get(key)
    if isinstance(value, list):
        if not value:
            return ""
        return _md("; ".join(str(item) for item in value))
    return _md(value)


def _md(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _records_from_mapping(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    return [dict(value)]


def _records_from_sequence(value: Any, *, rank_column: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    records: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        record = dict(item) if isinstance(item, dict) else {"value": item}
        if rank_column is not None:
            record = {rank_column: index, **record}
        records.append(record)
    return records


def _records_from_marker_mapping(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    records: list[dict[str, Any]] = []
    for marker_id, marker_value in value.items():
        record = {"marker_id": marker_id}
        if isinstance(marker_value, dict):
            record.update(marker_value)
        else:
            record["value"] = marker_value
        records.append(record)
    return records


def _records_from_artifact_paths(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    records: list[dict[str, Any]] = []
    for artifact_key, artifact_value in value.items():
        if isinstance(artifact_value, list):
            for item_index, item in enumerate(artifact_value, start=1):
                records.append(
                    {
                        "artifact_key": artifact_key,
                        "artifact_value": item,
                        "item_index": item_index,
                    }
                )
            continue
        records.append(
            {
                "artifact_key": artifact_key,
                "artifact_value": artifact_value,
                "item_index": pd.NA,
            }
        )
    return records


def _serialise_csv_value(value: Any) -> Any:
    if pd.isna(value) if not isinstance(value, (list, dict, tuple, set)) else False:
        return value
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def _select_peak_row(history: pd.DataFrame) -> pd.Series | None:
    if history.empty:
        return None
    sort_columns = [column for column in ["fused_failed_items", "total_backlog_demand", "service_level"] if column in history.columns]
    if not sort_columns:
        return history.iloc[0]
    ascending = [False, False, True][: len(sort_columns)]
    return history.sort_values(by=sort_columns, ascending=ascending).iloc[0]


def _build_network_time_series(network_history: pd.DataFrame) -> list[dict[str, Any]]:
    if network_history.empty:
        return []
    records = network_history.copy().to_dict("records")
    for record in records:
        if "date" in record:
            record["date"] = str(pd.Timestamp(record["date"]).date())
    return records
