from __future__ import annotations

import copy
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from supply_disruption_sim.data_adapter.raw_loader import load_raw_bundle
from supply_disruption_sim.data_adapter.standardizer import export_standard_bundle, standardize
from supply_disruption_sim.data_adapter.validator import validate_standard_bundle
from supply_disruption_sim.disruption.recovery_engine import run_simulation
from supply_disruption_sim.disruption.scenario_loader import (
    load_default_params,
    load_default_policies,
    load_scenario,
)
from supply_disruption_sim.labels import policy_profile_label
from supply_disruption_sim.model.builder import build_model
from supply_disruption_sim.reporting.report_generator import generate_report
from supply_disruption_sim.types import ModelBundle, PolicySpec, ReportArtifacts, SimulationParams, SimulationResult
from supply_disruption_sim.viz.network_trend_plot import build_network_history


DEFAULT_POLICY_PROFILES: dict[str, dict[str, dict[str, Any]]] = {
    "baseline": {},
    "all_policies": {
        "backup_supplier_switch": {"enabled": True},
        "equivalent_material_substitution": {"enabled": True},
        "priority_repair": {"enabled": True},
    },
    "no_policy": {
        "backup_supplier_switch": {"enabled": False},
        "equivalent_material_substitution": {"enabled": False},
        "priority_repair": {"enabled": False},
    },
    "only_backup_switch": {
        "backup_supplier_switch": {"enabled": True},
        "equivalent_material_substitution": {"enabled": False},
        "priority_repair": {"enabled": False},
    },
    "only_substitution": {
        "backup_supplier_switch": {"enabled": False},
        "equivalent_material_substitution": {"enabled": True},
        "priority_repair": {"enabled": False},
    },
    "only_priority_repair": {
        "backup_supplier_switch": {"enabled": False},
        "equivalent_material_substitution": {"enabled": False},
        "priority_repair": {"enabled": True},
    },
    "no_priority_repair": {"priority_repair": {"enabled": False}},
    "no_backup_switch": {"backup_supplier_switch": {"enabled": False}},
    "no_substitution": {"equivalent_material_substitution": {"enabled": False}},
}

DEFAULT_SINGLE_SCENARIO_COMPARISON_PROFILES = [
    "baseline",
    "all_policies",
    "no_policy",
    "only_backup_switch",
    "only_substitution",
    "only_priority_repair",
]


def prepare_experiment_context(
    input_dir: str | Path,
    standardized_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    input_path = Path(input_dir)
    raw_bundle = load_raw_bundle(input_path)
    standard_bundle = standardize(raw_bundle)
    report = validate_standard_bundle(standard_bundle)
    standardized_paths: dict[str, str] = {}
    if standardized_output_dir is not None:
        exported = export_standard_bundle(standard_bundle, standardized_output_dir)
        standardized_paths = {name: str(path) for name, path in exported.items()}
    if not report.is_valid:
        raise RuntimeError("Standardized bundle is invalid; run standardize and inspect the validation report first.")
    model = build_model(standard_bundle)
    return {
        "input_dir": str(input_path),
        "model": model,
        "validation_report": {
            "is_valid": report.is_valid,
            "issues": [
                {
                    "level": issue.level,
                    "check": issue.check,
                    "message": issue.message,
                    "details": issue.details,
                }
                for issue in report.issues
            ],
        },
        "standardized_paths": standardized_paths,
    }


def run_experiment(
    input_dir: str | Path,
    scenario_name: str,
    output_dir: str | Path,
    policy_profile: str = "baseline",
    report_profile: str = "minimal",
    policy_overrides: dict[str, dict[str, Any]] | None = None,
    custom_policy_profiles: dict[str, dict[str, dict[str, Any]]] | None = None,
    params_overrides: dict[str, Any] | None = None,
    standardized_output_dir: str | Path | None = None,
    include_parameter_experiments: bool = False,
) -> dict[str, Any]:
    context = prepare_experiment_context(
        input_dir=input_dir,
        standardized_output_dir=standardized_output_dir,
    )
    payload = run_experiment_with_model(
        model=context["model"],
        scenario_name=scenario_name,
        output_dir=output_dir,
        policy_profile=policy_profile,
        report_profile=report_profile,
        policy_overrides=policy_overrides,
        custom_policy_profiles=custom_policy_profiles,
        params_overrides=params_overrides,
        include_parameter_experiments=include_parameter_experiments,
    )
    payload["validation_report"] = context["validation_report"]
    payload["standardized_paths"] = context["standardized_paths"]
    return payload


def run_experiment_with_model(
    model: ModelBundle,
    scenario_name: str,
    output_dir: str | Path,
    policy_profile: str = "baseline",
    report_profile: str = "minimal",
    policy_overrides: dict[str, dict[str, Any]] | None = None,
    custom_policy_profiles: dict[str, dict[str, dict[str, Any]]] | None = None,
    params_overrides: dict[str, Any] | None = None,
    include_parameter_experiments: bool = False,
) -> dict[str, Any]:
    scenario = load_scenario(scenario_name, model)
    params = _build_params(model=model, params_overrides=params_overrides)
    policies = build_policy_set(
        policy_profile=policy_profile,
        policy_overrides=policy_overrides,
        custom_policy_profiles=custom_policy_profiles,
    )
    result = run_simulation(model=model, scenario=scenario, policies=policies, params=params)
    policy_comparison_summary, policy_comparison_time_series = _build_single_scenario_policy_comparison_outputs(
        model=model,
        scenario_name=scenario_name,
        baseline_result=result,
        baseline_policy_profile=policy_profile,
        params=params,
        custom_policy_profiles=custom_policy_profiles,
    )
    parameter_experiment_summary = None
    parameter_sensitivity_ranking = None
    if include_parameter_experiments:
        from supply_disruption_sim.experiment.sensitivity_runner import build_parameter_experiment_outputs

        parameter_experiment_summary, parameter_sensitivity_ranking = build_parameter_experiment_outputs(
            base_model=model,
            scenario_name=scenario_name,
            baseline_result=result,
            policy_profile=policy_profile,
            params_overrides=params_overrides,
            custom_policy_profiles=custom_policy_profiles,
        )
    artifacts = generate_report(
        result,
        output_dir,
        report_profile=report_profile,
        params=asdict(params),
        policy_comparison_summary=policy_comparison_summary,
        policy_comparison_time_series=policy_comparison_time_series,
        parameter_experiment_summary=parameter_experiment_summary,
        parameter_sensitivity_ranking=parameter_sensitivity_ranking,
    )
    return _serialize_experiment_payload(
        scenario_name=scenario_name,
        policy_profile=policy_profile,
        report_profile=report_profile,
        params=params,
        policies=policies,
        result=result,
        artifacts=artifacts,
    )


def build_policy_set(
    policy_profile: str = "baseline",
    policy_overrides: dict[str, dict[str, Any]] | None = None,
    custom_policy_profiles: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[PolicySpec]:
    policies = copy.deepcopy(load_default_policies())
    profile_overrides = _resolve_policy_profile(policy_profile, custom_policy_profiles)
    _apply_policy_overrides(policies, profile_overrides)
    _apply_policy_overrides(policies, policy_overrides or {})
    return policies


def _resolve_policy_profile(
    policy_profile: str,
    custom_policy_profiles: dict[str, dict[str, dict[str, Any]]] | None,
) -> dict[str, dict[str, Any]]:
    profiles = dict(DEFAULT_POLICY_PROFILES)
    if custom_policy_profiles:
        profiles.update(custom_policy_profiles)
    if policy_profile not in profiles:
        known = ", ".join(sorted(profiles))
        raise KeyError(f"Unknown policy profile '{policy_profile}'. Known profiles: {known}")
    return copy.deepcopy(profiles[policy_profile])


def _apply_policy_overrides(
    policies: list[PolicySpec],
    overrides: dict[str, dict[str, Any]],
) -> None:
    if not overrides:
        return
    policy_map = {policy.policy_type: policy for policy in policies}
    for policy_type, mutation in overrides.items():
        if policy_type not in policy_map:
            raise KeyError(f"Unknown policy type for override: {policy_type}")
        policy = policy_map[policy_type]
        for key, value in mutation.items():
            if key == "params":
                policy.params.update(dict(value))
                continue
            if key == "enabled":
                policy.enabled = bool(value)
                continue
            if key == "switch_time_days":
                policy.switch_time_days = int(value)
                continue
            if key == "priority_rule":
                policy.priority_rule = str(value)
                continue
            raise KeyError(f"Unsupported policy override field '{key}' for policy '{policy_type}'")


def _build_params(model: ModelBundle, params_overrides: dict[str, Any] | None) -> SimulationParams:
    params = load_default_params(model)
    if params_overrides:
        for key, value in params_overrides.items():
            if not hasattr(params, key):
                raise KeyError(f"Unknown simulation parameter override: {key}")
            setattr(params, key, value)
    _synchronize_bayesian_config(params)
    return params


def _synchronize_bayesian_config(params: SimulationParams) -> None:
    params.mode = "bayesian"
    params.bayesian_enabled = True
    params.bayesian_config = dict(params.bayesian_config or {})
    params.bayesian_config["mode"] = "bayesian"
    params.bayesian_config["enabled"] = True
    params.bayesian_config["use_sampling"] = bool(params.bayesian_use_sampling)
    params.bayesian_config["random_seed"] = int(params.bayesian_random_seed)


def _serialize_experiment_payload(
    scenario_name: str,
    policy_profile: str,
    report_profile: str,
    params: SimulationParams,
    policies: list[PolicySpec],
    result: SimulationResult,
    artifacts: ReportArtifacts,
) -> dict[str, Any]:
    return {
        "scenario_name": scenario_name,
        "scenario_id": result.scenario.scenario_id,
        "policy_profile": policy_profile,
        "report_profile": report_profile,
        "output_dir": str(artifacts.output_dir),
        "summary": result.summary,
        "params": asdict(params),
        "policies": [_serialize_policy(policy) for policy in policies],
        "artifacts": _serialize_artifacts(artifacts),
    }


def _serialize_policy(policy: PolicySpec) -> dict[str, Any]:
    return {
        "policy_type": policy.policy_type,
        "enabled": policy.enabled,
        "switch_time_days": policy.switch_time_days,
        "priority_rule": policy.priority_rule,
        "params": dict(policy.params),
    }


def _serialize_artifacts(artifacts: ReportArtifacts) -> dict[str, Any]:
    return {
        "output_dir": str(artifacts.output_dir),
        "tables_dir": str(artifacts.tables_dir) if artifacts.tables_dir else None,
        "figures_dir": str(artifacts.figures_dir) if artifacts.figures_dir else None,
        "history_csv": str(artifacts.history_csv),
        "item_history_csv": str(artifacts.item_history_csv) if artifacts.item_history_csv else None,
        "policy_events_csv": str(artifacts.policy_events_csv),
        "summary_csv": str(artifacts.summary_csv) if artifacts.summary_csv else None,
        "supply_history_csv": str(artifacts.supply_history_csv) if artifacts.supply_history_csv else None,
        "demand_history_csv": str(artifacts.demand_history_csv) if artifacts.demand_history_csv else None,
        "fusion_history_csv": str(artifacts.fusion_history_csv) if artifacts.fusion_history_csv else None,
        "network_history_csv": str(artifacts.network_history_csv) if artifacts.network_history_csv else None,
        "impacted_paths_csv": str(artifacts.impacted_paths_csv) if artifacts.impacted_paths_csv else None,
        "figure_path": str(artifacts.figure_path),
        "impact_figure_path": str(artifacts.impact_figure_path) if artifacts.impact_figure_path else None,
        "bom_figure_path": str(artifacts.bom_figure_path) if artifacts.bom_figure_path else None,
        "demand_figure_path": str(artifacts.demand_figure_path) if artifacts.demand_figure_path else None,
        "timeline_figure_path": str(artifacts.timeline_figure_path) if artifacts.timeline_figure_path else None,
        "policy_comparison_summary_csv": (
            str(artifacts.policy_comparison_summary_csv) if artifacts.policy_comparison_summary_csv else None
        ),
        "policy_comparison_time_series_csv": (
            str(artifacts.policy_comparison_time_series_csv) if artifacts.policy_comparison_time_series_csv else None
        ),
        "policy_comparison_figure_path": (
            str(artifacts.policy_comparison_figure_path) if artifacts.policy_comparison_figure_path else None
        ),
        "parameter_experiment_summary_csv": (
            str(artifacts.parameter_experiment_summary_csv) if artifacts.parameter_experiment_summary_csv else None
        ),
        "parameter_sensitivity_ranking_csv": (
            str(artifacts.parameter_sensitivity_ranking_csv) if artifacts.parameter_sensitivity_ranking_csv else None
        ),
        "parameter_sensitivity_figure_path": (
            str(artifacts.parameter_sensitivity_figure_path) if artifacts.parameter_sensitivity_figure_path else None
        ),
        "monthly_disrupted_nodes_figure_path": (
            str(artifacts.monthly_disrupted_nodes_figure_path)
            if artifacts.monthly_disrupted_nodes_figure_path
            else None
        ),
        "propagation_duration_figure_path": (
            str(artifacts.propagation_duration_figure_path) if artifacts.propagation_duration_figure_path else None
        ),
        "core_trends_figure_path": (
            str(artifacts.core_trends_figure_path) if artifacts.core_trends_figure_path else None
        ),
        "supplier_network_figure_path": (
            str(artifacts.supplier_network_figure_path) if artifacts.supplier_network_figure_path else None
        ),
        "material_network_figure_path": (
            str(artifacts.material_network_figure_path) if artifacts.material_network_figure_path else None
        ),
        "frontend_tables_dir": str(artifacts.frontend_tables_dir) if artifacts.frontend_tables_dir else None,
        "frontend_manifest_csv": str(artifacts.frontend_manifest_csv) if artifacts.frontend_manifest_csv else None,
        "network_snapshot_dir": str(artifacts.network_snapshot_dir) if artifacts.network_snapshot_dir else None,
        "network_snapshot_paths": [str(path) for path in artifacts.network_snapshot_paths],
    }


def _build_single_scenario_policy_comparison_outputs(
    *,
    model: ModelBundle,
    scenario_name: str,
    baseline_result: SimulationResult,
    baseline_policy_profile: str,
    params: SimulationParams,
    custom_policy_profiles: dict[str, dict[str, dict[str, Any]]] | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordered_profiles = list(DEFAULT_SINGLE_SCENARIO_COMPARISON_PROFILES)
    if baseline_policy_profile not in ordered_profiles:
        ordered_profiles.append(baseline_policy_profile)

    records: list[dict[str, Any]] = []
    comparison_frames: list[pd.DataFrame] = []
    _append_policy_comparison_result(
        result=baseline_result,
        policy_profile=baseline_policy_profile,
        summary_records=records,
        time_series_frames=comparison_frames,
    )
    for comparison_profile in ordered_profiles:
        if comparison_profile == baseline_policy_profile:
            continue
        comparison_scenario = load_scenario(scenario_name, model)
        comparison_policies = build_policy_set(
            policy_profile=comparison_profile,
            custom_policy_profiles=custom_policy_profiles,
        )
        comparison_result = run_simulation(
            model=model,
            scenario=comparison_scenario,
            policies=comparison_policies,
            params=copy.deepcopy(params),
        )
        _append_policy_comparison_result(
            result=comparison_result,
            policy_profile=comparison_profile,
            summary_records=records,
            time_series_frames=comparison_frames,
        )
    summary_df = pd.DataFrame(records)
    time_series_df = (
        pd.concat(comparison_frames, ignore_index=True)
        if comparison_frames
        else pd.DataFrame(columns=_policy_comparison_time_series_columns())
    )
    return (
        summary_df.sort_values(by=["scenario_id", "policy_profile"]).reset_index(drop=True),
        time_series_df.sort_values(by=["policy_profile", "date", "day_offset"]).reset_index(drop=True),
    )


def _append_policy_comparison_result(
    *,
    result: SimulationResult,
    policy_profile: str,
    summary_records: list[dict[str, Any]],
    time_series_frames: list[pd.DataFrame],
) -> None:
    summary_records.append(
        {
            "scenario_id": result.scenario.scenario_id,
            "policy_profile": policy_profile,
            "policy_label": policy_profile_label(policy_profile),
            **result.summary,
        }
    )
    time_series_frames.append(
        _build_policy_comparison_time_series_frame(
            result=result,
            policy_profile=policy_profile,
        )
    )


def _build_policy_comparison_time_series_frame(
    *,
    result: SimulationResult,
    policy_profile: str,
) -> pd.DataFrame:
    history = result.history.copy()
    if history.empty:
        return pd.DataFrame(columns=_policy_comparison_time_series_columns())

    history["date"] = pd.to_datetime(history["date"])
    network_history = build_network_history(result)
    if not network_history.empty:
        network_history["date"] = pd.to_datetime(network_history["date"])
        frame = history.merge(network_history, on="date", how="left", suffixes=("", "_network"))
    else:
        frame = history.copy()

    frame = frame.reset_index(drop=True)
    frame["scenario_id"] = result.scenario.scenario_id
    frame["policy_profile"] = str(policy_profile)
    frame["policy_label"] = policy_profile_label(policy_profile)
    frame["day_offset"] = frame.index.astype(int)
    for column in [
        "supplier_disrupted_nodes",
        "material_blocked_nodes",
        "assembly_blocked_nodes",
        "product_blocked_nodes",
    ]:
        if column not in frame.columns:
            frame[column] = 0
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0).astype(int)
    frame["downstream_interrupted_nodes"] = (
        frame["material_blocked_nodes"] + frame["assembly_blocked_nodes"] + frame["product_blocked_nodes"]
    )
    frame["total_interrupted_nodes"] = frame["supplier_disrupted_nodes"] + frame["downstream_interrupted_nodes"]

    missing_columns = [column for column in _policy_comparison_time_series_columns() if column not in frame.columns]
    for column in missing_columns:
        frame[column] = pd.NA
    return frame[_policy_comparison_time_series_columns()].copy()


def _policy_comparison_time_series_columns() -> list[str]:
    return [
        "scenario_id",
        "policy_profile",
        "policy_label",
        "date",
        "day_offset",
        "service_level",
        "system_service_level",
        "demand_fulfillment_rate",
        "active_backup_switches",
        "active_substitutions",
        "active_priority_repairs",
        "policy_cumulative_cost",
        "supplier_disrupted_nodes",
        "material_blocked_nodes",
        "assembly_blocked_nodes",
        "product_blocked_nodes",
        "downstream_interrupted_nodes",
        "total_interrupted_nodes",
    ]
