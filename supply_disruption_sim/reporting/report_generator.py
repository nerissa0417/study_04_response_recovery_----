from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd


matplotlib.use("Agg")

import matplotlib.pyplot as plt

from supply_disruption_sim.types import BatchReportArtifacts, ReportArtifacts, SimulationResult
from supply_disruption_sim.viz.bom_plot import export_bom_impact_plot
from supply_disruption_sim.viz.dashboard_data import export_dashboard_tables
from supply_disruption_sim.viz.disruption_analysis_plot import (
    export_batch_propagation_duration_comparison_figure,
    export_monthly_disrupted_nodes_comparison_figure,
    export_monthly_disrupted_nodes_figure,
    export_propagation_duration_figure,
    summarize_propagation_durations,
)
from supply_disruption_sim.viz.font_config import configure_matplotlib_chinese_font
from supply_disruption_sim.viz.network_snapshot import export_network_snapshots
from supply_disruption_sim.viz.network_trend_plot import (
    build_network_comparison_frame,
    build_network_history,
    export_core_metric_trends,
    export_material_network_comparison_figure,
    export_material_network_trends,
    export_supplier_network_comparison_figure,
    export_supplier_network_trends,
    export_timeline_comparison_figure,
)
from supply_disruption_sim.viz.timeline_plot import export_timeline_plot

CHINESE_FONT_NAME = configure_matplotlib_chinese_font()


def generate_report(
    result: SimulationResult,
    output_dir: str | Path,
    *,
    report_profile: str = "minimal",
    params: dict[str, Any] | None = None,
) -> ReportArtifacts:
    profile = _normalize_report_profile(report_profile)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    _cleanup_legacy_report_files(output_path)

    tables_dir = output_path / "tables"
    figures_dir = output_path / "figures"
    snapshot_dir = output_path / "network_snapshots"
    frontend_tables_dir = tables_dir / "frontend"
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    frontend_tables_dir.mkdir(parents=True, exist_ok=True)
    _clear_directory(frontend_tables_dir)

    history_csv = tables_dir / "history.csv"
    item_history_csv = tables_dir / "item_history.csv"
    policy_events_csv = tables_dir / "policy_events.csv"
    summary_csv = tables_dir / "summary.csv"
    supply_history_csv = tables_dir / "supply_history.csv"
    demand_history_csv = tables_dir / "demand_history.csv"
    fusion_history_csv = tables_dir / "fusion_history.csv"
    network_history_csv = tables_dir / "network_history.csv"
    impacted_paths_csv = tables_dir / "impacted_paths.csv"
    figure_path = figures_dir / "service_level.png"
    impact_figure_path = figures_dir / "impact_overview.png"
    bom_figure_path = figures_dir / "bom_impact_paths.png"
    timeline_figure_path = figures_dir / "timeline_overview.png"
    monthly_disrupted_nodes_figure_path = figures_dir / "monthly_disrupted_nodes.png"
    propagation_duration_figure_path = figures_dir / "propagation_duration_comparison.png"
    core_trends_figure_path = figures_dir / "core_metric_trends.png"
    supplier_network_figure_path = figures_dir / "supplier_network_trends.png"
    material_network_figure_path = figures_dir / "material_network_trends.png"
    frontend_manifest_csv = frontend_tables_dir / "manifest.csv"
    _clear_paths(
        [
            history_csv,
            item_history_csv,
            policy_events_csv,
            summary_csv,
            supply_history_csv,
            demand_history_csv,
            fusion_history_csv,
            network_history_csv,
            impacted_paths_csv,
            figure_path,
            impact_figure_path,
            bom_figure_path,
            timeline_figure_path,
            monthly_disrupted_nodes_figure_path,
            propagation_duration_figure_path,
            core_trends_figure_path,
            supplier_network_figure_path,
            material_network_figure_path,
            frontend_manifest_csv,
        ]
    )

    result.history.to_csv(history_csv, index=False)
    pd.DataFrame(result.policy_events).to_csv(policy_events_csv, index=False)
    pd.DataFrame(result.impacted_paths).to_csv(impacted_paths_csv, index=False)
    rendered_item_history_csv = None
    if _includes_full_outputs(profile):
        result.item_history.to_csv(item_history_csv, index=False)
        rendered_item_history_csv = item_history_csv
    network_history = build_network_history(result)
    result.summary.update(summarize_propagation_durations(result, network_history))
    network_history.to_csv(network_history_csv, index=False)
    pd.DataFrame([result.summary]).to_csv(summary_csv, index=False)
    rendered_supply_history_csv = None
    rendered_demand_history_csv = None
    rendered_fusion_history_csv = None
    rendered_service_level_path = None
    rendered_impact_figure_path = None
    rendered_timeline_path = None
    rendered_monthly_disrupted_nodes_path = export_monthly_disrupted_nodes_figure(
        result,
        network_history,
        monthly_disrupted_nodes_figure_path,
    )
    rendered_propagation_duration_path = export_propagation_duration_figure(
        result,
        network_history,
        propagation_duration_figure_path,
    )
    if _includes_full_outputs(profile):
        _select_supply_history(result.history).to_csv(supply_history_csv, index=False)
        _select_demand_history(result.history).to_csv(demand_history_csv, index=False)
        _select_fusion_history(result.history).to_csv(fusion_history_csv, index=False)
        rendered_supply_history_csv = supply_history_csv
        rendered_demand_history_csv = demand_history_csv
        rendered_fusion_history_csv = fusion_history_csv
    snapshot_paths = export_network_snapshots(result, snapshot_dir)
    if _includes_full_outputs(profile):
        _plot_service_level(result, figure_path)
        _plot_impact_overview(result, impact_figure_path)
        rendered_service_level_path = figure_path
        rendered_impact_figure_path = impact_figure_path
    rendered_bom_path = export_bom_impact_plot(result, bom_figure_path)
    if _includes_full_outputs(profile):
        rendered_timeline_path = export_timeline_plot(result, timeline_figure_path)
    rendered_core_trends_path = export_core_metric_trends(result, core_trends_figure_path)
    rendered_supplier_network_path = export_supplier_network_trends(
        result,
        network_history,
        supplier_network_figure_path,
    )
    rendered_material_network_path = export_material_network_trends(
        result,
        network_history,
        material_network_figure_path,
    )
    artifact_paths = _compact_artifact_paths(
        {
            "history_csv": history_csv,
            "item_history_csv": rendered_item_history_csv,
            "policy_events_csv": policy_events_csv,
            "summary_csv": summary_csv,
            "supply_history_csv": rendered_supply_history_csv,
            "demand_history_csv": rendered_demand_history_csv,
            "fusion_history_csv": rendered_fusion_history_csv,
            "network_history_csv": network_history_csv,
            "impacted_paths_csv": impacted_paths_csv,
            "service_level_figure": rendered_service_level_path,
            "impact_figure": rendered_impact_figure_path,
            "bom_figure": rendered_bom_path,
            "timeline_figure": rendered_timeline_path,
            "monthly_disrupted_nodes_figure": rendered_monthly_disrupted_nodes_path,
            "propagation_duration_figure": rendered_propagation_duration_path,
            "core_metric_trends_figure": rendered_core_trends_path,
            "supplier_network_trends_figure": rendered_supplier_network_path,
            "material_network_trends_figure": rendered_material_network_path,
            "network_snapshot_paths": [str(path) for path in snapshot_paths],
        }
    )
    artifact_paths["frontend_tables_dir"] = str(frontend_tables_dir)
    frontend_table_paths = export_dashboard_tables(
        result,
        frontend_tables_dir,
        artifact_paths=artifact_paths,
        network_history=network_history,
    )
    artifact_paths["frontend_manifest_csv"] = str(frontend_table_paths["manifest"])
    return ReportArtifacts(
        output_dir=output_path,
        tables_dir=tables_dir,
        figures_dir=figures_dir,
        history_csv=history_csv,
        policy_events_csv=policy_events_csv,
        summary_csv=summary_csv,
        item_history_csv=rendered_item_history_csv,
        supply_history_csv=rendered_supply_history_csv,
        demand_history_csv=rendered_demand_history_csv,
        fusion_history_csv=rendered_fusion_history_csv,
        network_history_csv=network_history_csv,
        impacted_paths_csv=impacted_paths_csv,
        figure_path=rendered_core_trends_path or core_trends_figure_path,
        impact_figure_path=rendered_impact_figure_path,
        bom_figure_path=rendered_bom_path,
        timeline_figure_path=rendered_timeline_path,
        monthly_disrupted_nodes_figure_path=rendered_monthly_disrupted_nodes_path,
        propagation_duration_figure_path=rendered_propagation_duration_path,
        core_trends_figure_path=rendered_core_trends_path,
        supplier_network_figure_path=rendered_supplier_network_path,
        material_network_figure_path=rendered_material_network_path,
        frontend_tables_dir=frontend_tables_dir,
        frontend_manifest_csv=frontend_table_paths["manifest"],
        network_snapshot_dir=snapshot_dir if snapshot_paths else None,
        network_snapshot_paths=snapshot_paths,
    )


def generate_batch_report(
    summary_df: pd.DataFrame,
    output_dir: str | Path,
    *,
    report_profile: str = "minimal",
) -> BatchReportArtifacts:
    profile = _normalize_report_profile(report_profile)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    tables_dir = output_path / "tables"
    figures_dir = output_path / "figures"
    paper_tables_dir = tables_dir / "paper"
    paper_figures_dir = figures_dir / "paper"
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    paper_tables_dir.mkdir(parents=True, exist_ok=True)
    paper_figures_dir.mkdir(parents=True, exist_ok=True)

    summary_csv = tables_dir / "experiment_summary.csv"
    policy_summary_csv = tables_dir / "policy_summary.csv"
    scenario_summary_csv = tables_dir / "scenario_summary.csv"
    network_comparison_csv = tables_dir / "network_comparison.csv"
    paper_scenario_policy_csv = paper_tables_dir / "scenario_policy_table.csv"
    paper_policy_effect_csv = paper_tables_dir / "policy_effect_table.csv"
    paper_policy_ranking_csv = paper_tables_dir / "policy_ranking_table.csv"
    paper_parameter_dimension_csv = paper_tables_dir / "parameter_dimension_table.csv"
    comparison_figure_path = figures_dir / "policy_comparison.png"
    scenario_figure_path = figures_dir / "scenario_comparison.png"
    timeline_comparison_figure_path = figures_dir / "timeline_comparison.png"
    supplier_network_comparison_figure_path = figures_dir / "supplier_network_comparison.png"
    material_network_comparison_figure_path = figures_dir / "material_network_comparison.png"
    monthly_disrupted_nodes_comparison_figure_path = figures_dir / "monthly_disrupted_nodes_comparison.png"
    propagation_duration_comparison_figure_path = figures_dir / "propagation_duration_comparison.png"
    paper_tradeoff_figure_path = paper_figures_dir / "policy_tradeoff.png"
    paper_summary_figure_path = paper_figures_dir / "paper_summary_panel.png"
    _clear_paths(
        [
            summary_csv,
            policy_summary_csv,
            scenario_summary_csv,
            network_comparison_csv,
            paper_scenario_policy_csv,
            paper_policy_effect_csv,
            paper_policy_ranking_csv,
            paper_parameter_dimension_csv,
            comparison_figure_path,
            scenario_figure_path,
            timeline_comparison_figure_path,
            supplier_network_comparison_figure_path,
            material_network_comparison_figure_path,
            monthly_disrupted_nodes_comparison_figure_path,
            propagation_duration_comparison_figure_path,
            paper_tradeoff_figure_path,
            paper_summary_figure_path,
        ]
    )

    enriched_summary = _attach_policy_comparison_metrics(summary_df)
    enriched_summary.to_csv(summary_csv, index=False)
    policy_summary = _aggregate_batch(enriched_summary, group_key="policy_profile")
    scenario_summary = _aggregate_batch(enriched_summary, group_key="scenario_id")
    policy_summary.to_csv(policy_summary_csv, index=False)
    scenario_summary.to_csv(scenario_summary_csv, index=False)
    paper_scenario_policy = _build_paper_scenario_policy_table(enriched_summary)
    paper_policy_effect = _build_paper_policy_effect_table(enriched_summary)
    paper_policy_ranking = _build_paper_policy_ranking_table(enriched_summary)
    paper_parameter_dimension = _build_paper_parameter_dimension_table(enriched_summary)
    network_comparison = build_network_comparison_frame(enriched_summary)
    network_comparison.to_csv(network_comparison_csv, index=False)
    rendered_policy_comparison_path = None
    rendered_scenario_comparison_path = None
    rendered_paper_scenario_policy_csv = None
    rendered_paper_policy_effect_csv = None
    rendered_paper_policy_ranking_csv = None
    rendered_paper_parameter_dimension_csv = None
    rendered_paper_tradeoff_figure_path = None
    rendered_paper_summary_figure_path = None
    if _includes_full_outputs(profile):
        _plot_batch_comparison(policy_summary, group_key="policy_profile", figure_path=comparison_figure_path)
        _plot_batch_comparison(scenario_summary, group_key="scenario_id", figure_path=scenario_figure_path)
        rendered_policy_comparison_path = comparison_figure_path
        rendered_scenario_comparison_path = scenario_figure_path
    if _includes_paper_outputs(profile):
        paper_scenario_policy.to_csv(paper_scenario_policy_csv, index=False)
        paper_policy_effect.to_csv(paper_policy_effect_csv, index=False)
        paper_policy_ranking.to_csv(paper_policy_ranking_csv, index=False)
        paper_parameter_dimension.to_csv(paper_parameter_dimension_csv, index=False)
        _plot_paper_tradeoff(enriched_summary, paper_tradeoff_figure_path)
        _plot_paper_summary_panel(paper_scenario_policy, paper_summary_figure_path)
        rendered_paper_scenario_policy_csv = paper_scenario_policy_csv
        rendered_paper_policy_effect_csv = paper_policy_effect_csv
        rendered_paper_policy_ranking_csv = paper_policy_ranking_csv
        rendered_paper_parameter_dimension_csv = paper_parameter_dimension_csv
        rendered_paper_tradeoff_figure_path = paper_tradeoff_figure_path
        rendered_paper_summary_figure_path = paper_summary_figure_path
    else:
        _plot_paper_tradeoff(enriched_summary, paper_tradeoff_figure_path)
        rendered_paper_tradeoff_figure_path = paper_tradeoff_figure_path
    rendered_timeline_comparison_path = export_timeline_comparison_figure(network_comparison, timeline_comparison_figure_path)
    rendered_supplier_network_comparison_path = export_supplier_network_comparison_figure(
        network_comparison,
        supplier_network_comparison_figure_path,
    )
    rendered_material_network_comparison_path = export_material_network_comparison_figure(
        network_comparison,
        material_network_comparison_figure_path,
    )
    rendered_monthly_disrupted_nodes_comparison_path = export_monthly_disrupted_nodes_comparison_figure(
        network_comparison,
        monthly_disrupted_nodes_comparison_figure_path,
    )
    rendered_propagation_duration_comparison_path = export_batch_propagation_duration_comparison_figure(
        enriched_summary,
        propagation_duration_comparison_figure_path,
    )
    artifact_paths = _compact_artifact_paths(
        {
            "summary_csv": summary_csv,
            "policy_summary_csv": policy_summary_csv,
            "scenario_summary_csv": scenario_summary_csv,
            "network_comparison_csv": network_comparison_csv,
            "comparison_figure_path": rendered_policy_comparison_path,
            "scenario_figure_path": rendered_scenario_comparison_path,
            "timeline_comparison_figure_path": rendered_timeline_comparison_path,
            "supplier_network_comparison_figure_path": rendered_supplier_network_comparison_path,
            "material_network_comparison_figure_path": rendered_material_network_comparison_path,
            "monthly_disrupted_nodes_comparison_figure_path": rendered_monthly_disrupted_nodes_comparison_path,
            "propagation_duration_comparison_figure_path": rendered_propagation_duration_comparison_path,
            "paper_scenario_policy_csv": rendered_paper_scenario_policy_csv,
            "paper_policy_effect_csv": rendered_paper_policy_effect_csv,
            "paper_policy_ranking_csv": rendered_paper_policy_ranking_csv,
            "paper_parameter_dimension_csv": rendered_paper_parameter_dimension_csv,
            "paper_tradeoff_figure_path": rendered_paper_tradeoff_figure_path,
            "paper_summary_figure_path": rendered_paper_summary_figure_path,
        }
    )

    return BatchReportArtifacts(
        output_dir=output_path,
        summary_csv=summary_csv,
        tables_dir=tables_dir,
        figures_dir=figures_dir,
        network_comparison_csv=network_comparison_csv,
        scenario_summary_csv=scenario_summary_csv,
        policy_summary_csv=policy_summary_csv,
        comparison_figure_path=rendered_policy_comparison_path,
        scenario_figure_path=rendered_scenario_comparison_path,
        timeline_comparison_figure_path=rendered_timeline_comparison_path,
        supplier_network_comparison_figure_path=rendered_supplier_network_comparison_path,
        material_network_comparison_figure_path=rendered_material_network_comparison_path,
        monthly_disrupted_nodes_comparison_figure_path=rendered_monthly_disrupted_nodes_comparison_path,
        propagation_duration_comparison_figure_path=rendered_propagation_duration_comparison_path,
        paper_scenario_policy_csv=rendered_paper_scenario_policy_csv,
        paper_policy_effect_csv=rendered_paper_policy_effect_csv,
        paper_policy_ranking_csv=rendered_paper_policy_ranking_csv,
        paper_parameter_dimension_csv=rendered_paper_parameter_dimension_csv,
        paper_tradeoff_figure_path=rendered_paper_tradeoff_figure_path,
        paper_summary_figure_path=rendered_paper_summary_figure_path,
    )


def _plot_service_level(result: SimulationResult, figure_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(
        result.history["date"],
        result.history["service_level"],
        color="#0F6F5C",
        linewidth=2,
        label="产品服务水平",
    )
    if "demand_fulfillment_rate" in result.history:
        ax.plot(
            result.history["date"],
            result.history["demand_fulfillment_rate"],
            color="#F28C28",
            linewidth=1.8,
            label="需求满足率",
        )
    if "system_service_level" in result.history:
        ax.plot(
            result.history["date"],
            result.history["system_service_level"],
            color="#7A4EAB",
            linewidth=1.8,
            label="融合服务水平",
        )
    ax.set_title(f"服务水平曲线：{result.scenario.scenario_id}")
    ax.set_xlabel("日期")
    ax.set_ylabel("服务水平")
    ax.set_ylim(-0.05, 1.05)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower left")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)


def _plot_impact_overview(result: SimulationResult, figure_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    series = [
        ("供应不可用物料数", "supply_effective_unavailable_items", "#9E2A2B"),
        ("总积压需求", "total_backlog_demand", "#E09F3E"),
        ("融合失败物料数", "fused_failed_items", "#540B0E"),
    ]
    for label, column, color in series:
        if column in result.history:
            ax.plot(result.history["date"], result.history[column], linewidth=2, label=label, color=color)
    ax.set_title(f"影响概览：{result.scenario.scenario_id}")
    ax.set_xlabel("日期")
    ax.set_ylabel("影响强度")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)


def _select_supply_history(history: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "date",
        "active_suppliers",
        "disrupted_suppliers",
        "degraded_suppliers",
        "supply_effective_affected_items",
        "supply_effective_degraded_items",
        "supply_effective_unavailable_items",
        "final_product_status",
        "service_level",
        "active_backup_switches",
        "active_substitutions",
        "supply_available_items",
        "supply_degraded_items",
        "supply_unavailable_items",
        "supply_blocked_assemblies",
        "supply_affected_products",
        "supply_failed_products",
        "policy_daily_cost",
        "policy_cumulative_cost",
        "backup_supplier_switch_cumulative_cost",
        "equivalent_material_substitution_cumulative_cost",
        "priority_repair_cumulative_cost",
    ]
    return history[[column for column in columns if column in history.columns]].copy()


def _select_demand_history(history: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "date",
        "total_requested_demand",
        "total_fulfilled_demand",
        "total_backlog_demand",
        "total_lost_demand",
        "demand_fulfillment_rate",
        "demand_backlog_items",
        "demand_lost_items",
        "demand_backlog_products",
        "demand_lost_products",
    ]
    return history[[column for column in columns if column in history.columns]].copy()


def _select_fusion_history(history: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "date",
        "fused_active_items",
        "fused_affected_items",
        "fused_failed_items",
        "fused_active_products",
        "fused_affected_products",
        "fused_failed_products",
        "system_service_level",
        "system_root_cause",
        "root_cause_supply_constraint_items",
        "root_cause_demand_items",
        "root_cause_mixed_items",
        "root_cause_supply_constraint_products",
        "root_cause_demand_products",
        "root_cause_mixed_products",
    ]
    return history[[column for column in columns if column in history.columns]].copy()


def _aggregate_batch(summary_df: pd.DataFrame, group_key: str) -> pd.DataFrame:
    if summary_df.empty or group_key not in summary_df.columns:
        return pd.DataFrame(columns=[group_key, "experiment_count"])
    numeric_columns = summary_df.select_dtypes(include="number").columns.tolist()
    aggregated = (
        summary_df.groupby(group_key, dropna=False)[numeric_columns]
        .mean(numeric_only=True)
        .round(4)
        .reset_index()
    )
    counts = summary_df.groupby(group_key, dropna=False).size().rename("experiment_count").reset_index()
    return counts.merge(aggregated, on=group_key, how="left")


def _plot_batch_comparison(summary_df: pd.DataFrame, group_key: str, figure_path: Path) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    metrics = [
        ("average_service_level", "平均服务水平"),
        ("ttr_days", "恢复时间（天）"),
        ("policy_total_cost", "平均策略成本"),
        ("benefit_vs_reference", "相对参考收益"),
        ("net_benefit_vs_reference", "相对参考净收益"),
        ("policy_cost_benefit_ratio_vs_reference", "相对参考成本收益比"),
    ]
    for ax, (metric, title) in zip(axes.flat, metrics):
        if metric not in summary_df.columns or summary_df.empty:
            ax.set_axis_off()
            continue
        ax.bar(summary_df[group_key].astype(str), summary_df[metric], color="#2A6F97")
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=20)
        ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)


def _build_paper_scenario_policy_table(summary_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "scenario_id",
        "policy_profile",
        "target_id",
        "ttr_days",
        "failed_days",
        "affected_days",
        "average_service_level",
        "avg_system_service_level",
        "estimated_disruption_loss",
        "policy_total_cost",
        "benefit_vs_reference",
        "net_benefit_vs_reference",
        "policy_cost_benefit_ratio_vs_reference",
        "average_service_level_gain_vs_reference",
        "ttr_improvement_days_vs_reference",
        "dominant_root_cause_at_max_business_impact",
    ]
    table = summary_df[[column for column in columns if column in summary_df.columns]].copy()
    if not table.empty and {"scenario_id", "policy_profile"}.issubset(table.columns):
        table = table.sort_values(by=["scenario_id", "policy_profile"]).reset_index(drop=True)
    return table


def _build_paper_policy_effect_table(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df.empty or "policy_profile" not in summary_df.columns:
        return pd.DataFrame(
            columns=[
                "policy_profile",
                "scenario_count",
                "mean_average_service_level",
                "mean_ttr_days",
                "mean_estimated_disruption_loss",
                "mean_policy_total_cost",
                "mean_net_benefit_vs_reference",
                "best_service_scenario_count",
                "best_ttr_scenario_count",
                "best_net_benefit_scenario_count",
            ]
        )

    records: list[dict] = []
    best_service_index = (
        summary_df.groupby("scenario_id")["average_service_level"].idxmax()
        if {"scenario_id", "average_service_level"}.issubset(summary_df.columns)
        else pd.Index([])
    )
    best_ttr_index = (
        summary_df.groupby("scenario_id")["ttr_days"].idxmin()
        if {"scenario_id", "ttr_days"}.issubset(summary_df.columns)
        else pd.Index([])
    )
    best_net_benefit_index = (
        summary_df.groupby("scenario_id")["net_benefit_vs_reference"].idxmax()
        if {"scenario_id", "net_benefit_vs_reference"}.issubset(summary_df.columns)
        else pd.Index([])
    )

    for policy_profile, group in summary_df.groupby("policy_profile", dropna=False):
        record = {
            "policy_profile": policy_profile,
            "scenario_count": int(group["scenario_id"].nunique()) if "scenario_id" in group.columns else int(len(group)),
            "mean_average_service_level": round(float(group["average_service_level"].mean()), 4)
            if "average_service_level" in group.columns
            else pd.NA,
            "mean_ttr_days": round(float(group["ttr_days"].mean()), 4) if "ttr_days" in group.columns else pd.NA,
            "mean_estimated_disruption_loss": round(float(group["estimated_disruption_loss"].mean()), 4)
            if "estimated_disruption_loss" in group.columns
            else pd.NA,
            "mean_policy_total_cost": round(float(group["policy_total_cost"].mean()), 4)
            if "policy_total_cost" in group.columns
            else pd.NA,
            "mean_net_benefit_vs_reference": round(float(group["net_benefit_vs_reference"].mean()), 4)
            if "net_benefit_vs_reference" in group.columns
            else pd.NA,
            "best_service_scenario_count": int(group.index.isin(best_service_index).sum()),
            "best_ttr_scenario_count": int(group.index.isin(best_ttr_index).sum()),
            "best_net_benefit_scenario_count": int(group.index.isin(best_net_benefit_index).sum()),
        }
        records.append(record)
    return pd.DataFrame(records).sort_values(by="policy_profile").reset_index(drop=True)


def _build_paper_policy_ranking_table(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df.empty or "scenario_id" not in summary_df.columns or "policy_profile" not in summary_df.columns:
        return pd.DataFrame(columns=["scenario_id", "policy_profile", "paper_composite_score", "paper_rank"])

    records: list[dict] = []
    for scenario_id, group in summary_df.groupby("scenario_id", dropna=False):
        working = group.copy()
        score_columns: list[str] = []
        if "average_service_level" in working.columns:
            working["score_service"] = _normalize_series(working["average_service_level"], higher_is_better=True)
            score_columns.append("score_service")
        if "ttr_days" in working.columns:
            working["score_ttr"] = _normalize_series(working["ttr_days"], higher_is_better=False)
            score_columns.append("score_ttr")
        if "estimated_disruption_loss" in working.columns:
            working["score_loss"] = _normalize_series(working["estimated_disruption_loss"], higher_is_better=False)
            score_columns.append("score_loss")
        if "net_benefit_vs_reference" in working.columns:
            working["score_net_benefit"] = _normalize_series(
                working["net_benefit_vs_reference"],
                higher_is_better=True,
            )
            score_columns.append("score_net_benefit")
        if "policy_total_cost" in working.columns:
            working["score_cost"] = _normalize_series(working["policy_total_cost"], higher_is_better=False)
            score_columns.append("score_cost")
        if not score_columns:
            continue
        working["paper_composite_score"] = working[score_columns].mean(axis=1).round(4)
        working["paper_rank"] = working["paper_composite_score"].rank(method="dense", ascending=False).astype(int)
        records.extend(
            working[
                ["scenario_id", "policy_profile", "paper_composite_score", "paper_rank"] + score_columns
            ].sort_values(by=["paper_rank", "policy_profile"])
            .to_dict("records")
        )
    return pd.DataFrame(records)


def _build_paper_parameter_dimension_table(summary_df: pd.DataFrame) -> pd.DataFrame:
    dimension_columns = [
        column
        for column in summary_df.columns
        if column.startswith("applied_") or column in {"parameter_name", "parameter_value", "applied_parameter_value"}
    ]
    if summary_df.empty or not dimension_columns:
        return pd.DataFrame(
            columns=[
                "dimension_name",
                "dimension_value",
                "experiment_count",
                "average_service_level",
                "ttr_days",
                "estimated_disruption_loss",
                "policy_total_cost",
            ]
        )

    records: list[dict] = []
    for column in dimension_columns:
        if summary_df[column].isna().all():
            continue
        grouped = summary_df.loc[summary_df[column].notna()].groupby(column, dropna=False)
        for dimension_value, group in grouped:
            records.append(
                {
                    "dimension_name": column,
                    "dimension_value": dimension_value,
                    "experiment_count": int(len(group)),
                    "average_service_level": round(float(group["average_service_level"].mean()), 4)
                    if "average_service_level" in group.columns
                    else pd.NA,
                    "ttr_days": round(float(group["ttr_days"].mean()), 4) if "ttr_days" in group.columns else pd.NA,
                    "estimated_disruption_loss": round(float(group["estimated_disruption_loss"].mean()), 4)
                    if "estimated_disruption_loss" in group.columns
                    else pd.NA,
                    "policy_total_cost": round(float(group["policy_total_cost"].mean()), 4)
                    if "policy_total_cost" in group.columns
                    else pd.NA,
                }
            )
    return pd.DataFrame(records)


def _plot_paper_tradeoff(summary_df: pd.DataFrame, figure_path: Path) -> None:
    if summary_df.empty or not {"policy_total_cost", "estimated_disruption_loss"}.issubset(summary_df.columns):
        return
    fig, ax = plt.subplots(figsize=(10, 6))
    scenario_ids = summary_df["scenario_id"].astype(str).unique().tolist() if "scenario_id" in summary_df.columns else ["all"]
    cmap = plt.get_cmap("tab10", max(len(scenario_ids), 1))
    color_map = {scenario_id: cmap(index) for index, scenario_id in enumerate(scenario_ids)}

    for _, row in summary_df.iterrows():
        scenario_id = str(row.get("scenario_id", "all"))
        ax.scatter(
            float(row["policy_total_cost"]),
            float(row["estimated_disruption_loss"]),
            color=color_map.get(scenario_id),
            s=80,
            alpha=0.85,
        )
        ax.annotate(
            str(row.get("policy_profile", "")),
            (float(row["policy_total_cost"]), float(row["estimated_disruption_loss"])),
            textcoords="offset points",
            xytext=(6, 4),
            fontsize=8,
        )

    handles = [
        plt.Line2D([0], [0], marker="o", color="w", label=scenario_id, markerfacecolor=color_map[scenario_id], markersize=8)
        for scenario_id in scenario_ids
    ]
    if handles:
        ax.legend(handles=handles, loc="upper right")
    ax.set_title("论文摘要图：策略成本-损失权衡")
    ax.set_xlabel("策略总成本")
    ax.set_ylabel("估计中断损失")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)


def _plot_paper_summary_panel(summary_df: pd.DataFrame, figure_path: Path) -> None:
    if summary_df.empty or not {"scenario_id", "policy_profile"}.issubset(summary_df.columns):
        return
    labels = summary_df.apply(lambda row: f"{row['scenario_id']}\n{row['policy_profile']}", axis=1)
    metrics = [
        ("average_service_level", "平均服务水平"),
        ("ttr_days", "恢复时间"),
        ("estimated_disruption_loss", "估计中断损失"),
        ("net_benefit_vs_reference", "相对参考净收益"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    for ax, (metric, title) in zip(axes.flat, metrics):
        if metric not in summary_df.columns:
            ax.set_axis_off()
            continue
        ax.bar(labels, summary_df[metric], color="#5C80BC")
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=18)
        ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)


def _normalize_series(series: pd.Series, *, higher_is_better: bool) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.dropna().empty:
        return pd.Series([pd.NA] * len(series), index=series.index, dtype="object")
    minimum = float(numeric.min())
    maximum = float(numeric.max())
    if abs(maximum - minimum) <= 1e-9:
        return pd.Series([1.0] * len(series), index=series.index, dtype="float64")
    normalized = (numeric - minimum) / (maximum - minimum)
    if higher_is_better:
        return normalized.round(4)
    return (1 - normalized).round(4)


def _attach_policy_comparison_metrics(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df.empty:
        return summary_df.copy()

    enriched = summary_df.copy()
    for column in [
        "reference_policy_profile",
        "reference_policy_total_cost",
        "reference_estimated_disruption_loss",
        "incremental_cost_vs_reference",
        "benefit_vs_reference",
        "net_benefit_vs_reference",
        "policy_cost_benefit_ratio_vs_reference",
        "average_service_level_gain_vs_reference",
        "ttr_improvement_days_vs_reference",
    ]:
        enriched[column] = pd.NA

    required_columns = {"scenario_id", "policy_profile", "policy_total_cost", "estimated_disruption_loss"}
    if not required_columns.issubset(enriched.columns):
        return enriched

    for scenario_id, group in enriched.groupby("scenario_id", dropna=False):
        reference = (
            group.sort_values(
                by=["policy_total_cost", "estimated_disruption_loss", "policy_profile"],
                ascending=[True, False, True],
            )
            .iloc[0]
        )
        reference_profile = str(reference["policy_profile"])
        reference_cost = float(reference["policy_total_cost"])
        reference_loss = float(reference["estimated_disruption_loss"])
        reference_service = float(reference["average_service_level"]) if "average_service_level" in group.columns else 0.0
        reference_ttr = float(reference["ttr_days"]) if pd.notna(reference.get("ttr_days")) else pd.NA

        for index, row in group.iterrows():
            current_cost = float(row["policy_total_cost"])
            current_loss = float(row["estimated_disruption_loss"])
            incremental_cost = current_cost - reference_cost
            benefit = reference_loss - current_loss
            net_benefit = benefit - incremental_cost
            ratio = benefit / incremental_cost if incremental_cost > 0 else pd.NA
            enriched.at[index, "reference_policy_profile"] = reference_profile
            enriched.at[index, "reference_policy_total_cost"] = round(reference_cost, 4)
            enriched.at[index, "reference_estimated_disruption_loss"] = round(reference_loss, 4)
            enriched.at[index, "incremental_cost_vs_reference"] = round(incremental_cost, 4)
            enriched.at[index, "benefit_vs_reference"] = round(benefit, 4)
            enriched.at[index, "net_benefit_vs_reference"] = round(net_benefit, 4)
            enriched.at[index, "policy_cost_benefit_ratio_vs_reference"] = (
                round(float(ratio), 4) if pd.notna(ratio) else pd.NA
            )
            if "average_service_level" in group.columns:
                enriched.at[index, "average_service_level_gain_vs_reference"] = round(
                    float(row["average_service_level"]) - reference_service,
                    4,
                )
            if "ttr_days" in group.columns and pd.notna(reference_ttr) and pd.notna(row.get("ttr_days")):
                enriched.at[index, "ttr_improvement_days_vs_reference"] = round(
                    float(reference_ttr) - float(row["ttr_days"]),
                    4,
                )
    for column in [
        "reference_policy_total_cost",
        "reference_estimated_disruption_loss",
        "incremental_cost_vs_reference",
        "benefit_vs_reference",
        "net_benefit_vs_reference",
        "policy_cost_benefit_ratio_vs_reference",
        "average_service_level_gain_vs_reference",
        "ttr_improvement_days_vs_reference",
    ]:
        enriched[column] = pd.to_numeric(enriched[column], errors="coerce")
    return enriched


def _cleanup_legacy_report_files(output_path: Path) -> None:
    for legacy_name in ["history.csv", "item_history.csv", "service_level.png"]:
        legacy_path = output_path / legacy_name
        if legacy_path.exists():
            legacy_path.unlink()


def _normalize_report_profile(report_profile: str) -> str:
    profile = str(report_profile or "minimal").strip().lower()
    if profile not in {"minimal", "full", "paper"}:
        raise ValueError(f"Unsupported report profile: {report_profile}")
    return profile


def _includes_full_outputs(report_profile: str) -> bool:
    return report_profile in {"full", "paper"}


def _includes_paper_outputs(report_profile: str) -> bool:
    return report_profile == "paper"


def _compact_artifact_paths(artifact_paths: dict[str, object]) -> dict[str, object]:
    compacted: dict[str, object] = {}
    for key, value in artifact_paths.items():
        if value is None:
            continue
        if isinstance(value, Path):
            compacted[key] = str(value)
            continue
        compacted[key] = value
    return compacted


def _clear_paths(paths: list[Path]) -> None:
    for path in paths:
        if path.exists():
            path.unlink()


def _clear_directory(directory: Path) -> None:
    if not directory.exists():
        return
    for path in directory.iterdir():
        if path.is_file():
            path.unlink()
