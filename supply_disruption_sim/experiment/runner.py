from __future__ import annotations

import copy
from dataclasses import asdict
from pathlib import Path
from typing import Any

from supply_disruption_sim.data_adapter.raw_loader import load_raw_bundle
from supply_disruption_sim.data_adapter.standardizer import export_standard_bundle, standardize
from supply_disruption_sim.data_adapter.validator import validate_standard_bundle
from supply_disruption_sim.disruption.recovery_engine import run_simulation
from supply_disruption_sim.disruption.scenario_loader import (
    load_default_params,
    load_default_policies,
    load_scenario,
)
from supply_disruption_sim.model.builder import build_model
from supply_disruption_sim.reporting.report_generator import generate_report
from supply_disruption_sim.types import ModelBundle, PolicySpec, ReportArtifacts, SimulationParams, SimulationResult


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
) -> dict[str, Any]:
    scenario = load_scenario(scenario_name, model)
    params = _build_params(model=model, params_overrides=params_overrides)
    policies = build_policy_set(
        policy_profile=policy_profile,
        policy_overrides=policy_overrides,
        custom_policy_profiles=custom_policy_profiles,
    )
    result = run_simulation(model=model, scenario=scenario, policies=policies, params=params)
    artifacts = generate_report(result, output_dir, report_profile=report_profile, params=asdict(params))
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
        "timeline_figure_path": str(artifacts.timeline_figure_path) if artifacts.timeline_figure_path else None,
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
        "network_snapshot_dir": str(artifacts.network_snapshot_dir) if artifacts.network_snapshot_dir else None,
        "network_snapshot_paths": [str(path) for path in artifacts.network_snapshot_paths],
    }
