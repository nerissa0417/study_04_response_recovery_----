from __future__ import annotations

import copy
import math
import random
from dataclasses import asdict
from pathlib import Path
from typing import Any

import matplotlib
import pandas as pd


matplotlib.use("Agg")

import matplotlib.pyplot as plt

from supply_disruption_sim.disruption.recovery_engine import run_simulation
from supply_disruption_sim.disruption.scenario_loader import load_default_params, load_scenario
from supply_disruption_sim.experiment.runner import build_policy_set, prepare_experiment_context
from supply_disruption_sim.labels import parameter_dimension_label, parameter_label, policy_profile_label, scenario_label
from supply_disruption_sim.model.builder import build_model
from supply_disruption_sim.reporting.report_generator import generate_report
from supply_disruption_sim.types import ModelBundle, PolicySpec, ScenarioSpec, SimulationParams, StandardBundle
from supply_disruption_sim.viz.plot_theme import add_figure_header, finish_figure, font_props, style_axes


DEFAULT_SENSITIVITY_PARAMETER_GRID: dict[str, list[float | int]] = {
    "single_source_ratio": [0.7, 0.85, 1.0],
    "backup_coverage": [0.0, 0.5, 1.0],
    "substitution_availability": [0.0, 0.5, 1.0],
    "backup_switch_time_days": [3, 7, 14],
    "priority_repair_lead_days": [2, 5, 8],
    "incident_duration_factor": [0.75, 1.0, 1.5],
}

DEFAULT_SENSITIVITY_METRICS = [
    "average_service_level",
    "ttr_days",
    "estimated_disruption_loss",
    "policy_total_cost",
]

FORMAL_PARAMETER_EXPERIMENT_GRID: dict[str, list[float | int]] = {
    "backup_coverage": [0.0, 0.5, 1.0],
    "substitution_availability": [0.0, 0.5, 1.0],
    "backup_switch_time_days": [3, 7, 14],
    "priority_repair_lead_days": [2, 5, 8],
}


def run_sensitivity_analysis(
    input_dir: str | Path,
    scenario_name: str,
    output_dir: str | Path,
    policy_profile: str = "time_priority_interrupt",
    parameter_grid: dict[str, list[float | int]] | None = None,
    standardized_output_dir: str | Path | None = None,
    random_seed: int = 42,
    params_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_path = Path(output_dir)
    tables_dir = output_path / "tables"
    figures_dir = output_path / "figures"
    runs_dir = output_path / "runs"
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    context = prepare_experiment_context(
        input_dir=input_dir,
        standardized_output_dir=standardized_output_dir,
    )
    base_model = context["model"]
    grid = parameter_grid or dict(DEFAULT_SENSITIVITY_PARAMETER_GRID)

    baseline_payload = _run_parameter_variant(
        base_model=base_model,
        scenario_name=scenario_name,
        policy_profile=policy_profile,
        output_dir=runs_dir / "baseline",
        parameter_values={},
        random_seed=random_seed,
        params_overrides=params_overrides,
    )

    records = [baseline_payload["record"]]
    for parameter_name, values in grid.items():
        for index, value in enumerate(values):
            payload = _run_parameter_variant(
                base_model=base_model,
                scenario_name=scenario_name,
                policy_profile=policy_profile,
                output_dir=runs_dir / f"{parameter_name}_{_slugify(str(value))}",
                parameter_values={parameter_name: value},
                random_seed=random_seed + index,
                params_overrides=params_overrides,
            )
            records.append(payload["record"])

    runs_df = pd.DataFrame(records)
    parameter_response_df = _build_parameter_response(runs_df)
    baseline_row = runs_df.loc[runs_df["parameter_name"] == "baseline"].iloc[0].to_dict()
    sensitivity_ranking_df = _rank_sensitivity(parameter_response_df, baseline_row)

    runs_csv = tables_dir / "sensitivity_runs.csv"
    parameter_response_csv = tables_dir / "parameter_response.csv"
    sensitivity_ranking_csv = tables_dir / "sensitivity_ranking.csv"
    ranking_figure = figures_dir / "sensitivity_ranking.png"

    runs_df.to_csv(runs_csv, index=False)
    parameter_response_df.to_csv(parameter_response_csv, index=False)
    sensitivity_ranking_df.to_csv(sensitivity_ranking_csv, index=False)
    _plot_sensitivity_ranking(sensitivity_ranking_df, ranking_figure)

    return {
        "output_dir": str(output_path),
        "standardized_paths": context["standardized_paths"],
        "validation_report": context["validation_report"],
        "runs_csv": str(runs_csv),
        "parameter_response_csv": str(parameter_response_csv),
        "sensitivity_ranking_csv": str(sensitivity_ranking_csv),
        "ranking_figure": str(ranking_figure),
    }


def build_parameter_experiment_outputs(
    *,
    base_model: ModelBundle,
    scenario_name: str,
    baseline_result,
    policy_profile: str = "time_priority_interrupt",
    parameter_grid: dict[str, list[float | int]] | None = None,
    random_seed: int = 42,
    params_overrides: dict[str, Any] | None = None,
    custom_policy_profiles: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    grid = parameter_grid or dict(FORMAL_PARAMETER_EXPERIMENT_GRID)
    baseline_record = _build_parameter_experiment_record(
        result=baseline_result,
        policy_profile=policy_profile,
        parameter_name="baseline",
        parameter_value=pd.NA,
        applied_parameter_value=pd.NA,
    )
    records = [baseline_record]

    for parameter_name, values in grid.items():
        for index, value in enumerate(values):
            variant_model, scenario, params, policies, applied_parameters = prepare_variant_inputs(
                base_model=base_model,
                scenario_name=scenario_name,
                policy_profile=policy_profile,
                parameter_values={parameter_name: value},
                random_seed=random_seed + index,
                params_overrides=params_overrides,
                custom_policy_profiles=custom_policy_profiles,
            )
            result = run_simulation(
                model=variant_model,
                scenario=scenario,
                policies=policies,
                params=params,
            )
            records.append(
                _build_parameter_experiment_record(
                    result=result,
                    policy_profile=policy_profile,
                    parameter_name=parameter_name,
                    parameter_value=value,
                    applied_parameter_value=applied_parameters.get(parameter_name, value),
                )
            )

    runs_df = pd.DataFrame(records)
    parameter_response_df = _build_parameter_response(runs_df)
    ranking_df = _rank_sensitivity(parameter_response_df, baseline_record)
    summary_df = _build_parameter_experiment_summary(runs_df, baseline_record)
    return summary_df, ranking_df


def _run_parameter_variant(
    *,
    base_model: ModelBundle,
    scenario_name: str,
    policy_profile: str,
    output_dir: Path,
    parameter_values: dict[str, float | int],
    random_seed: int,
    params_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    variant_model, scenario, params, policies, applied_parameters = prepare_variant_inputs(
        base_model=base_model,
        scenario_name=scenario_name,
        policy_profile=policy_profile,
        parameter_values=parameter_values,
        random_seed=random_seed,
        params_overrides=params_overrides,
    )
    result = run_simulation(
        model=variant_model,
        scenario=scenario,
        policies=policies,
        params=params,
    )
    artifacts = generate_report(result, output_dir, params=asdict(params))
    record = {
        "scenario_name": scenario_name,
        "scenario_id": result.scenario.scenario_id,
        "policy_profile": policy_profile,
        "parameter_name": next(iter(parameter_values), "baseline"),
        "parameter_value": next(iter(parameter_values.values()), pd.NA),
        "applied_parameter_value": next(iter(applied_parameters.values()), pd.NA) if applied_parameters else pd.NA,
        "run_output_dir": str(artifacts.output_dir),
        "history_csv": str(artifacts.history_csv),
        "figure_path": str(artifacts.figure_path),
    }
    for parameter_name, value in applied_parameters.items():
        record[f"applied_{parameter_name}"] = value
    record.update(result.summary)
    return {"record": record, "artifacts": artifacts}


def prepare_variant_inputs(
    *,
    base_model: ModelBundle,
    scenario_name: str,
    policy_profile: str,
    parameter_values: dict[str, float | int],
    random_seed: int = 42,
    params_overrides: dict[str, Any] | None = None,
    custom_policy_profiles: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> tuple[ModelBundle, ScenarioSpec, SimulationParams, list[PolicySpec], dict[str, float | int]]:
    bundle = copy.deepcopy(base_model.standard_bundle)
    applied_parameters: dict[str, float | int] = {}

    _apply_structural_variations(bundle=bundle, parameter_values=parameter_values, random_seed=random_seed)
    variant_model = build_model(bundle)
    scenario = load_scenario(scenario_name, variant_model)
    params = load_default_params(variant_model)
    _apply_param_overrides(params, params_overrides)
    policies = build_policy_set(
        policy_profile=policy_profile,
        custom_policy_profiles=custom_policy_profiles,
    )

    if "incident_duration_factor" in parameter_values:
        duration_factor = max(float(parameter_values["incident_duration_factor"]), 0.1)
        scenario.duration_days = max(1, int(round(scenario.duration_days * duration_factor)))
        applied_parameters["incident_duration_factor"] = round(duration_factor, 4)

    if "priority_repair_lead_days" in parameter_values:
        params.priority_repair_lead_days = max(1, int(parameter_values["priority_repair_lead_days"]))
        applied_parameters["priority_repair_lead_days"] = params.priority_repair_lead_days

    if "backup_switch_time_days" in parameter_values:
        switch_time_days = max(0, int(parameter_values["backup_switch_time_days"]))
        for policy in policies:
            if policy.policy_type == "backup_supplier_switch":
                policy.switch_time_days = switch_time_days
        applied_parameters["backup_switch_time_days"] = switch_time_days

    if "single_source_ratio" in parameter_values:
        applied_parameters["single_source_ratio"] = round(_measure_single_source_ratio(bundle), 4)
    if "backup_coverage" in parameter_values:
        applied_parameters["backup_coverage"] = round(_measure_backup_coverage(bundle), 4)
    if "substitution_availability" in parameter_values:
        applied_parameters["substitution_availability"] = round(
            min(max(float(parameter_values["substitution_availability"]), 0.0), 1.0),
            4,
        )

    return variant_model, scenario, params, policies, applied_parameters


def _apply_param_overrides(params: SimulationParams, params_overrides: dict[str, Any] | None) -> None:
    if params_overrides:
        for key, value in params_overrides.items():
            if not hasattr(params, key):
                raise KeyError(f"Unknown simulation parameter override: {key}")
            setattr(params, key, value)
    params.mode = "bayesian"
    params.bayesian_enabled = True
    params.bayesian_config = dict(params.bayesian_config or {})
    params.bayesian_config["mode"] = "bayesian"
    params.bayesian_config["enabled"] = True
    params.bayesian_config["use_sampling"] = bool(params.bayesian_use_sampling)
    params.bayesian_config["random_seed"] = int(params.bayesian_random_seed)


def _apply_structural_variations(
    *,
    bundle: StandardBundle,
    parameter_values: dict[str, float | int],
    random_seed: int,
) -> None:
    if not parameter_values:
        return

    if "single_source_ratio" in parameter_values:
        _apply_single_source_ratio(
            bundle=bundle,
            target_ratio=float(parameter_values["single_source_ratio"]),
            random_seed=random_seed,
        )
    if "backup_coverage" in parameter_values:
        _apply_backup_coverage(
            bundle=bundle,
            target_coverage=float(parameter_values["backup_coverage"]),
            random_seed=random_seed,
        )
    if "substitution_availability" in parameter_values:
        _apply_substitution_availability(
            bundle=bundle,
            target_availability=float(parameter_values["substitution_availability"]),
        )
    if "backup_switch_time_days" in parameter_values:
        switch_time_days = max(0, int(parameter_values["backup_switch_time_days"]))
        mask = bundle.supplier_item_map["is_backup"].astype(bool)
        bundle.supplier_item_map.loc[mask, "switch_time_days"] = switch_time_days


def _apply_single_source_ratio(bundle: StandardBundle, target_ratio: float, random_seed: int) -> None:
    target_ratio = min(max(float(target_ratio), 0.0), 1.0)
    supply_map = bundle.supplier_item_map.copy()
    ranked_items = _rank_items(bundle)
    item_ids = [item_id for item_id in ranked_items if item_id in set(supply_map["item_id"])]
    target_multi_count = int(round((1.0 - target_ratio) * len(item_ids)))

    current_source_mask = ~supply_map["is_backup"].astype(bool)
    current_multi_items = {
        item_id
        for item_id, count in supply_map.loc[current_source_mask].groupby("item_id").size().to_dict().items()
        if int(count) > 1
    }
    if len(current_multi_items) > target_multi_count:
        keep_multi_items = set(item_ids[:target_multi_count])
        for item_id in sorted(current_multi_items - keep_multi_items):
            rows = supply_map.loc[
                (supply_map["item_id"] == item_id) & (~supply_map["is_backup"].astype(bool))
            ].sort_values(
                by=["share", "supplier_id"],
                ascending=[False, True],
            )
            for row_index in rows.index[1:]:
                supply_map.at[row_index, "is_primary"] = False
                supply_map.at[row_index, "is_backup"] = True
                supply_map.at[row_index, "is_current_source"] = False
                supply_map.at[row_index, "share"] = 0.0
                supply_map.at[row_index, "backup_capacity_factor"] = max(
                    float(supply_map.at[row_index, "backup_capacity_factor"]),
                    0.75,
                )
    elif len(current_multi_items) < target_multi_count:
        supplier_quality = _build_supplier_quality(bundle)
        for item_id in item_ids:
            if len(current_multi_items) >= target_multi_count:
                break
            rows = supply_map.loc[supply_map["item_id"] == item_id]
            primary_rows = rows.loc[rows["is_primary"]]
            if len(primary_rows) > 1 or rows.empty:
                continue
            backup_rows = rows.loc[rows["is_backup"]]
            if not backup_rows.empty:
                promote_index = backup_rows.sort_values(
                    by=["qualified_rate", "avg_capacity", "supplier_id"],
                    ascending=[False, False, True],
                ).index[0]
                supply_map.at[promote_index, "is_primary"] = True
                supply_map.at[promote_index, "is_backup"] = False
                supply_map.at[promote_index, "is_current_source"] = True
                supply_map.at[promote_index, "share"] = max(float(supply_map.at[promote_index, "share"]), 0.35)
                current_multi_items.add(item_id)
                continue
            synthetic_row = _build_supply_row(
                bundle=bundle,
                item_id=item_id,
                current_item_rows=rows,
                supplier_quality=supplier_quality,
                as_backup=False,
                random_seed=random_seed,
            )
            if synthetic_row is None:
                continue
            supply_map = pd.concat([supply_map, pd.DataFrame([synthetic_row])], ignore_index=True)
            current_multi_items.add(item_id)

    bundle.supplier_item_map = _normalize_supply_map_flags(supply_map)


def _apply_backup_coverage(bundle: StandardBundle, target_coverage: float, random_seed: int) -> None:
    target_coverage = min(max(float(target_coverage), 0.0), 1.0)
    supply_map = bundle.supplier_item_map.copy()
    ranked_items = _rank_items(bundle)
    item_ids = [item_id for item_id in ranked_items if item_id in set(supply_map["item_id"])]
    target_backup_count = int(round(target_coverage * len(item_ids)))
    current_backup_items = {
        item_id
        for item_id, count in supply_map.loc[supply_map["is_backup"]].groupby("item_id").size().to_dict().items()
        if int(count) > 0
    }

    if len(current_backup_items) > target_backup_count:
        keep_backup_items = set(item_ids[:target_backup_count])
        for item_id in sorted(current_backup_items - keep_backup_items):
            mask = (supply_map["item_id"] == item_id) & (supply_map["is_backup"])
            supply_map.loc[mask, "is_backup"] = False
            supply_map.loc[mask, "is_current_source"] = True
            supply_map.loc[mask, "backup_capacity_factor"] = 1.0
    elif len(current_backup_items) < target_backup_count:
        supplier_quality = _build_supplier_quality(bundle)
        for item_id in item_ids:
            if len(current_backup_items) >= target_backup_count:
                break
            rows = supply_map.loc[supply_map["item_id"] == item_id]
            if rows.empty or item_id in current_backup_items:
                continue
            secondary_rows = rows.loc[~rows["is_primary"]]
            if not secondary_rows.empty:
                backup_index = secondary_rows.sort_values(
                    by=["qualified_rate", "avg_capacity", "supplier_id"],
                    ascending=[False, False, True],
                ).index[0]
                supply_map.at[backup_index, "is_backup"] = True
                supply_map.at[backup_index, "is_current_source"] = False
                supply_map.at[backup_index, "share"] = 0.0
                supply_map.at[backup_index, "backup_capacity_factor"] = max(
                    float(supply_map.at[backup_index, "backup_capacity_factor"]),
                    0.75,
                )
                current_backup_items.add(item_id)
                continue
            synthetic_row = _build_supply_row(
                bundle=bundle,
                item_id=item_id,
                current_item_rows=rows,
                supplier_quality=supplier_quality,
                as_backup=True,
                random_seed=random_seed,
            )
            if synthetic_row is None:
                continue
            supply_map = pd.concat([supply_map, pd.DataFrame([synthetic_row])], ignore_index=True)
            current_backup_items.add(item_id)

    bundle.supplier_item_map = _normalize_supply_map_flags(supply_map)


def _apply_substitution_availability(bundle: StandardBundle, target_availability: float) -> None:
    target_availability = min(max(float(target_availability), 0.0), 1.0)
    part_alternatives = bundle.part_alternatives.copy()
    if part_alternatives.empty:
        return
    target_count = int(round(target_availability * len(part_alternatives)))
    ranked = part_alternatives.sort_values(
        by=["priority", "item_id", "alt_item_id"],
        ascending=[True, True, True],
    )
    bundle.part_alternatives = ranked.head(target_count).reset_index(drop=True)


def _normalize_supply_map_flags(supply_map: pd.DataFrame) -> pd.DataFrame:
    normalized = supply_map.copy().reset_index(drop=True)
    normalized["is_primary"] = normalized["is_primary"].astype(bool)
    normalized["is_backup"] = normalized["is_backup"].astype(bool)
    if "is_current_source" not in normalized.columns:
        normalized["is_current_source"] = ~normalized["is_backup"]
    normalized["is_current_source"] = normalized["is_current_source"].fillna(~normalized["is_backup"]).astype(bool)
    normalized.loc[normalized["is_primary"], "is_backup"] = False
    normalized.loc[normalized["is_backup"], "is_current_source"] = False
    normalized.loc[~normalized["is_backup"], "is_current_source"] = True
    for column, default in {
        "backup_priority": 99,
        "supply_role": "unknown",
        "mapping_origin": "unknown",
    }.items():
        if column not in normalized.columns:
            normalized[column] = default
        normalized[column] = normalized[column].fillna(default)
    normalized["share"] = pd.to_numeric(normalized["share"], errors="coerce").fillna(0.0)
    normalized.loc[normalized["is_backup"], "share"] = 0.0
    normalized["is_primary"] = False
    for item_id, group in normalized.loc[~normalized["is_backup"]].groupby("item_id", sort=False):
        if group.empty:
            continue
        total_share = float(group["share"].sum())
        if total_share <= 0:
            normalized.loc[group.index, "share"] = 1.0 / len(group.index)
        elif abs(total_share - 1.0) > 0.0001:
            normalized.loc[group.index, "share"] = group["share"] / total_share
        primary_index = normalized.loc[group.index].sort_values(
            by=["share", "supplier_id"],
            ascending=[False, True],
        ).index[0]
        normalized.loc[primary_index, "is_primary"] = True
    normalized["edge_status_default"] = normalized["is_backup"].map({True: "standby", False: "active"})
    normalized.loc[~normalized["is_backup"], "backup_capacity_factor"] = normalized.loc[
        ~normalized["is_backup"], "backup_capacity_factor"
    ].fillna(1.0)
    return normalized


def _build_supplier_quality(bundle: StandardBundle) -> pd.DataFrame:
    quality = bundle.suppliers[
        ["supplier_id", "region_id", "compliance_rate", "default_rate", "historical_incident_count"]
    ].copy()
    quality["candidate_score"] = (
        quality["compliance_rate"].astype(float) * 2.0
        - quality["default_rate"].astype(float)
        - quality["historical_incident_count"].astype(float) * 0.05
    )
    return quality.sort_values(by=["candidate_score", "supplier_id"], ascending=[False, True]).reset_index(drop=True)


def _build_supply_row(
    *,
    bundle: StandardBundle,
    item_id: str,
    current_item_rows: pd.DataFrame,
    supplier_quality: pd.DataFrame,
    as_backup: bool,
    random_seed: int,
) -> dict[str, Any] | None:
    del random_seed
    items = bundle.items.set_index("item_id")
    if item_id not in items.index:
        return None
    current_suppliers = set(current_item_rows["supplier_id"].tolist())
    candidate_pool = supplier_quality.loc[~supplier_quality["supplier_id"].isin(current_suppliers)]
    primary_supplier_id = None
    if not current_item_rows.empty:
        primary_rows = current_item_rows.loc[current_item_rows["is_primary"]].sort_values(
            by=["share", "supplier_id"],
            ascending=[False, True],
        )
        if not primary_rows.empty:
            primary_supplier_id = str(primary_rows.iloc[0]["supplier_id"])
    preferred_region = None
    if primary_supplier_id is not None:
        region_series = bundle.suppliers.loc[bundle.suppliers["supplier_id"] == primary_supplier_id, "region_id"]
        if not region_series.empty:
            preferred_region = region_series.iloc[0]
    if preferred_region is not None:
        same_region = candidate_pool.loc[candidate_pool["region_id"] == preferred_region]
        if not same_region.empty:
            candidate_pool = pd.concat(
                [same_region, candidate_pool.loc[candidate_pool["region_id"] != preferred_region]],
                ignore_index=True,
            )
    if candidate_pool.empty:
        return None

    supplier_row = candidate_pool.iloc[0]
    item_row = items.loc[item_id]
    return {
        "supplier_id": supplier_row["supplier_id"],
        "item_id": item_id,
        "share": 0.35 if not as_backup else 0.0,
        "is_primary": not as_backup,
        "is_backup": as_backup,
        "is_current_source": not as_backup,
        "avg_capacity": max(float(item_row["avg_daily_demand"]) * (1.1 if as_backup else 1.0), 1.0),
        "qualified_rate": float(supplier_row["compliance_rate"]),
        "delay_rate": max(0.03, float(supplier_row["default_rate"]) / 2),
        "estimated_lead_time_days": 7,
        "switch_time_days": 7 if as_backup else 0,
        "qualification_required": bool(as_backup),
        "qualification_time_days": 5 if as_backup else 0,
        "backup_capacity_factor": 0.75 if as_backup else 1.0,
        "backup_priority": 90 if as_backup else 0,
        "mapping_origin": "synthetic_backup" if as_backup else "synthetic_primary",
        "supply_role": "synthetic_backup" if as_backup else "synthetic_current",
        "edge_type": "supplier_item_map",
        "edge_status_default": "standby" if as_backup else "active",
    }


def _rank_items(bundle: StandardBundle) -> list[str]:
    ranked = bundle.items.copy().sort_values(
        by=["is_final_product", "is_critical_material", "avg_daily_demand", "item_id"],
        ascending=[False, False, False, True],
    )
    return ranked["item_id"].tolist()


def _measure_single_source_ratio(bundle: StandardBundle) -> float:
    item_count = max(int(bundle.supplier_item_map["item_id"].nunique()), 1)
    active_counts = bundle.supplier_item_map.loc[~bundle.supplier_item_map["is_backup"].astype(bool)].groupby("item_id").size()
    single_source_count = int((active_counts <= 1).sum()) + max(0, item_count - int(active_counts.shape[0]))
    return single_source_count / item_count


def _measure_backup_coverage(bundle: StandardBundle) -> float:
    item_count = max(int(bundle.supplier_item_map["item_id"].nunique()), 1)
    backup_items = int(bundle.supplier_item_map.loc[bundle.supplier_item_map["is_backup"], "item_id"].nunique())
    return backup_items / item_count


def _build_parameter_experiment_record(
    *,
    result,
    policy_profile: str,
    parameter_name: str,
    parameter_value: float | int | Any,
    applied_parameter_value: float | int | Any,
) -> dict[str, Any]:
    return {
        "scenario_id": result.scenario.scenario_id,
        "scenario_name": scenario_label(result.scenario.scenario_id),
        "policy_profile": policy_profile,
        "policy_profile_name": policy_profile_label(policy_profile),
        "parameter_name": parameter_name,
        "parameter_label": parameter_label(parameter_name),
        "dimension_label": parameter_dimension_label(parameter_name),
        "parameter_value": parameter_value,
        "applied_parameter_value": applied_parameter_value,
        **result.summary,
    }


def _build_parameter_experiment_summary(
    runs_df: pd.DataFrame,
    baseline_row: dict[str, Any],
) -> pd.DataFrame:
    if runs_df.empty:
        return pd.DataFrame(
            columns=[
                "scenario_id",
                "scenario_name",
                "policy_profile",
                "policy_profile_name",
                "dimension_label",
                "parameter_name",
                "parameter_label",
                "parameter_value",
                "applied_parameter_value",
                "parameter_value_label",
                "ttr_days",
                "failed_days",
                "affected_days",
                "avg_system_service_level",
                "estimated_disruption_loss",
                "policy_total_cost",
                "ttr_change_days",
                "avg_system_service_level_change",
                "estimated_disruption_loss_change",
                "policy_total_cost_change",
            ]
        )

    working = runs_df.loc[runs_df["parameter_name"] != "baseline"].copy()
    if working.empty:
        return pd.DataFrame()

    baseline_ttr = pd.to_numeric(pd.Series([baseline_row.get("ttr_days")]), errors="coerce").iloc[0]
    baseline_system_service = pd.to_numeric(pd.Series([baseline_row.get("avg_system_service_level")]), errors="coerce").iloc[0]
    baseline_loss = pd.to_numeric(pd.Series([baseline_row.get("estimated_disruption_loss")]), errors="coerce").iloc[0]
    baseline_cost = pd.to_numeric(pd.Series([baseline_row.get("policy_total_cost")]), errors="coerce").iloc[0]

    numeric_columns = [
        "parameter_value",
        "applied_parameter_value",
        "ttr_days",
        "failed_days",
        "affected_days",
        "avg_system_service_level",
        "estimated_disruption_loss",
        "policy_total_cost",
    ]
    for column in numeric_columns:
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce")

    working["parameter_value_label"] = working.apply(
        lambda row: _format_parameter_value(
            parameter_name=str(row["parameter_name"]),
            parameter_value=row["applied_parameter_value"]
            if pd.notna(row["applied_parameter_value"])
            else row["parameter_value"],
        ),
        axis=1,
    )
    working["ttr_change_days"] = (working["ttr_days"] - baseline_ttr).round(4)
    working["avg_system_service_level_change"] = (working["avg_system_service_level"] - baseline_system_service).round(4)
    working["estimated_disruption_loss_change"] = (working["estimated_disruption_loss"] - baseline_loss).round(4)
    working["policy_total_cost_change"] = (working["policy_total_cost"] - baseline_cost).round(4)
    dimension_order = {
        "节点能力": 0,
        "协同平台支撑能力": 1,
        "场景扰动强度": 2,
    }
    parameter_order = {name: index for index, name in enumerate(FORMAL_PARAMETER_EXPERIMENT_GRID)}
    working["dimension_order"] = working["dimension_label"].map(dimension_order).fillna(99)
    working["parameter_order"] = working["parameter_name"].map(parameter_order).fillna(99)
    working = working.sort_values(
        by=["dimension_order", "parameter_order", "parameter_value"],
        ascending=[True, True, True],
    )
    return working[
        [
            "scenario_id",
            "scenario_name",
            "policy_profile",
            "policy_profile_name",
            "dimension_label",
            "parameter_name",
            "parameter_label",
            "parameter_value",
            "applied_parameter_value",
            "parameter_value_label",
            "ttr_days",
            "failed_days",
            "affected_days",
            "avg_system_service_level",
            "estimated_disruption_loss",
            "policy_total_cost",
            "ttr_change_days",
            "avg_system_service_level_change",
            "estimated_disruption_loss_change",
            "policy_total_cost_change",
        ]
    ].reset_index(drop=True)


def _format_parameter_value(*, parameter_name: str, parameter_value: Any) -> str:
    if pd.isna(parameter_value):
        return "基准值"
    numeric_value = pd.to_numeric(pd.Series([parameter_value]), errors="coerce").iloc[0]
    if pd.isna(numeric_value):
        return str(parameter_value)
    if str(parameter_name) in {"backup_switch_time_days", "priority_repair_lead_days"}:
        return f"{int(round(float(numeric_value)))}天"
    return f"{float(numeric_value):.2f}"


def _build_parameter_response(runs_df: pd.DataFrame) -> pd.DataFrame:
    if runs_df.empty:
        return pd.DataFrame()
    parameter_rows = runs_df.loc[runs_df["parameter_name"] != "baseline"].copy()
    if parameter_rows.empty:
        return pd.DataFrame()
    group_cols = ["parameter_name", "parameter_value", "applied_parameter_value"]
    numeric_cols = parameter_rows.select_dtypes(include="number").columns.tolist()
    return (
        parameter_rows.groupby(group_cols, dropna=False)[numeric_cols]
        .mean(numeric_only=True)
        .round(4)
        .reset_index()
        .sort_values(by=["parameter_name", "parameter_value"], ascending=[True, True])
    )


def _rank_sensitivity(parameter_response_df: pd.DataFrame, baseline_row: dict[str, Any]) -> pd.DataFrame:
    if parameter_response_df.empty:
        return pd.DataFrame(columns=["parameter_name", "sensitivity_score"])

    records: list[dict[str, Any]] = []
    for parameter_name, group in parameter_response_df.groupby("parameter_name", dropna=False):
        metric_impacts: dict[str, float] = {}
        for metric in DEFAULT_SENSITIVITY_METRICS:
            if metric not in group.columns:
                continue
            baseline_value = baseline_row.get(metric)
            if baseline_value is None or pd.isna(baseline_value):
                continue
            baseline_scale = abs(float(baseline_value)) if abs(float(baseline_value)) > 1e-9 else 1.0
            metric_range = float(group[metric].max()) - float(group[metric].min())
            metric_impacts[f"{metric}_impact"] = round(metric_range / baseline_scale, 4)
        if not metric_impacts:
            continue
        records.append(
            {
                "parameter_name": parameter_name,
                "sensitivity_score": round(sum(metric_impacts.values()) / len(metric_impacts), 4),
                **metric_impacts,
            }
        )
    return pd.DataFrame(records).sort_values(by="sensitivity_score", ascending=False).reset_index(drop=True)


def _plot_sensitivity_ranking(sensitivity_ranking_df: pd.DataFrame, figure_path: Path) -> None:
    if sensitivity_ranking_df.empty:
        return
    working = sensitivity_ranking_df.copy()
    working["parameter_label"] = working["parameter_name"].map(parameter_label)
    fig, ax = plt.subplots(figsize=(10.2, 4.8))
    fig.patch.set_facecolor("#FFFFFF")
    fig.suptitle(
        "参数敏感度排序",
        x=0.08,
        y=0.98,
        ha="left",
        color="#12263A",
        fontproperties=font_props(size=19, weight="bold"),
    )
    fig.text(
        0.08,
        0.90,
        "比较不同能力参数对恢复结果的综合影响强弱",
        ha="left",
        va="top",
        color="#5B6B7A",
        fontproperties=font_props(size=12.2),
    )
    fig.subplots_adjust(left=0.22, right=0.95, bottom=0.14, top=0.78)
    ax.barh(
        working["parameter_label"],
        working["sensitivity_score"],
        color="#2563EB",
        alpha=0.92,
    )
    style_axes(ax, xlabel="综合敏感度得分", ylabel="参数维度", grid_axis="x")
    ax.invert_yaxis()
    for index, value in enumerate(pd.to_numeric(working["sensitivity_score"], errors="coerce").fillna(0.0)):
        ax.text(
            float(value) + 0.01,
            index,
            f"{float(value):.3f}",
            va="center",
            ha="left",
            color="#12263A",
            fontproperties=font_props(size=9.4),
        )
    finish_figure(fig, figure_path, top=0.93, tight=False)


def _slugify(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-", "."} else "_" for char in value).strip("_") or "run"
