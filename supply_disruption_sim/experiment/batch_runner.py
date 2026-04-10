from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from supply_disruption_sim.experiment.runner import prepare_experiment_context, run_experiment_with_model
from supply_disruption_sim.reporting.report_generator import generate_batch_report


DEFAULT_BATCH_POLICY_PROFILES = [
    "baseline",
    "all_policies",
    "no_policy",
    "only_backup_switch",
    "only_substitution",
    "only_priority_repair",
]


def run_batch_experiments(
    input_dir: str | Path,
    scenarios: list[str],
    output_dir: str | Path,
    policy_profiles: list[str] | None = None,
    report_profile: str = "minimal",
    custom_policy_profiles: dict[str, dict[str, dict[str, Any]]] | None = None,
    params_overrides: dict[str, Any] | None = None,
    standardized_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    context = prepare_experiment_context(
        input_dir=input_dir,
        standardized_output_dir=standardized_output_dir,
    )
    model = context["model"]
    run_root = output_path / "runs"
    run_root.mkdir(parents=True, exist_ok=True)

    selected_profiles = policy_profiles or list(DEFAULT_BATCH_POLICY_PROFILES)
    records: list[dict[str, Any]] = []
    run_payloads: list[dict[str, Any]] = []

    for scenario_name in scenarios:
        for policy_profile in selected_profiles:
            run_output_dir = run_root / f"{_slugify(scenario_name)}__{_slugify(policy_profile)}"
            payload = run_experiment_with_model(
                model=model,
                scenario_name=scenario_name,
                output_dir=run_output_dir,
                policy_profile=policy_profile,
                report_profile=report_profile,
                custom_policy_profiles=custom_policy_profiles,
                params_overrides=params_overrides,
            )
            run_payloads.append(payload)
            record = {
                "scenario_name": scenario_name,
                "scenario_id": payload["scenario_id"],
                "policy_profile": policy_profile,
                "run_output_dir": payload["output_dir"],
                "summary_json": payload["artifacts"]["summary_json"],
                "history_csv": payload["artifacts"]["history_csv"],
                "network_history_csv": payload["artifacts"]["network_history_csv"],
                "figure_path": payload["artifacts"]["figure_path"],
                "network_snapshot_count": len(payload["artifacts"]["network_snapshot_paths"]),
            }
            record.update(payload["summary"])
            records.append(record)

    summary_df = pd.DataFrame(records)
    batch_artifacts = generate_batch_report(summary_df, output_path, report_profile=report_profile)
    return {
        "output_dir": str(output_path),
        "report_profile": report_profile,
        "standardized_paths": context["standardized_paths"],
        "validation_report": context["validation_report"],
        "summary_csv": str(batch_artifacts.summary_csv),
        "summary_json": str(batch_artifacts.summary_json),
        "policy_summary_csv": (
            str(batch_artifacts.policy_summary_csv) if batch_artifacts.policy_summary_csv else None
        ),
        "scenario_summary_csv": (
            str(batch_artifacts.scenario_summary_csv) if batch_artifacts.scenario_summary_csv else None
        ),
        "network_comparison_csv": (
            str(batch_artifacts.network_comparison_csv) if batch_artifacts.network_comparison_csv else None
        ),
        "comparison_figure_path": (
            str(batch_artifacts.comparison_figure_path) if batch_artifacts.comparison_figure_path else None
        ),
        "scenario_figure_path": (
            str(batch_artifacts.scenario_figure_path) if batch_artifacts.scenario_figure_path else None
        ),
        "timeline_comparison_figure_path": (
            str(batch_artifacts.timeline_comparison_figure_path)
            if batch_artifacts.timeline_comparison_figure_path
            else None
        ),
        "supplier_network_comparison_figure_path": (
            str(batch_artifacts.supplier_network_comparison_figure_path)
            if batch_artifacts.supplier_network_comparison_figure_path
            else None
        ),
        "material_network_comparison_figure_path": (
            str(batch_artifacts.material_network_comparison_figure_path)
            if batch_artifacts.material_network_comparison_figure_path
            else None
        ),
        "monthly_disrupted_nodes_comparison_figure_path": (
            str(batch_artifacts.monthly_disrupted_nodes_comparison_figure_path)
            if batch_artifacts.monthly_disrupted_nodes_comparison_figure_path
            else None
        ),
        "propagation_duration_comparison_figure_path": (
            str(batch_artifacts.propagation_duration_comparison_figure_path)
            if batch_artifacts.propagation_duration_comparison_figure_path
            else None
        ),
        "paper_scenario_policy_csv": (
            str(batch_artifacts.paper_scenario_policy_csv) if batch_artifacts.paper_scenario_policy_csv else None
        ),
        "paper_policy_effect_csv": (
            str(batch_artifacts.paper_policy_effect_csv) if batch_artifacts.paper_policy_effect_csv else None
        ),
        "paper_policy_ranking_csv": (
            str(batch_artifacts.paper_policy_ranking_csv) if batch_artifacts.paper_policy_ranking_csv else None
        ),
        "paper_parameter_dimension_csv": (
            str(batch_artifacts.paper_parameter_dimension_csv)
            if batch_artifacts.paper_parameter_dimension_csv
            else None
        ),
        "paper_tradeoff_figure_path": (
            str(batch_artifacts.paper_tradeoff_figure_path) if batch_artifacts.paper_tradeoff_figure_path else None
        ),
        "paper_summary_figure_path": (
            str(batch_artifacts.paper_summary_figure_path) if batch_artifacts.paper_summary_figure_path else None
        ),
        "runs": run_payloads,
    }


def build_experiment_summary_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(records)


def _slugify(value: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z._-]+", "_", value).strip("_")
    return sanitized or "run"
