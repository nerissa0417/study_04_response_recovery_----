from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from supply_disruption_sim.disruption.recovery_engine import run_simulation
from supply_disruption_sim.disruption.scenario_loader import load_default_params, load_scenario
from supply_disruption_sim.experiment.runner import (
    build_policy_comparison_outputs_for_scenario,
    build_policy_set,
    prepare_experiment_context,
)
from supply_disruption_sim.types import ModelBundle, PolicySpec, ReportArtifacts, ScenarioSpec, SimulationParams, SimulationResult


REFERENCE_SCENE_TEMPLATES = {
    "random": "default_random_distributed_node_disruption",
    "keynode": "default_keynode_distributed_disruption",
}


def load_interactive_context(input_dir: str | Path) -> dict[str, Any]:
    context = prepare_experiment_context(input_dir=input_dir)
    model = context["model"]
    reference_scenarios = {
        family: load_scenario(template_name, model)
        for family, template_name in REFERENCE_SCENE_TEMPLATES.items()
    }
    return {
        **context,
        "reference_scenarios": reference_scenarios,
    }


def build_custom_node_scenario(
    *,
    model: ModelBundle,
    node_key: str | list[str],
    scene_family: str,
    reference_scenarios: dict[str, ScenarioSpec] | None = None,
    severity: float = 1.0,
) -> ScenarioSpec:
    family = scene_family.strip().lower()
    if family not in REFERENCE_SCENE_TEMPLATES:
        known = ", ".join(sorted(REFERENCE_SCENE_TEMPLATES))
        raise KeyError(f"Unknown scene family '{scene_family}'. Known families: {known}")

    if reference_scenarios and family in reference_scenarios:
        reference = reference_scenarios[family]
    else:
        reference = load_scenario(REFERENCE_SCENE_TEMPLATES[family], model)

    supplier_ids: list[str] = []
    item_ids: list[str] = []
    node_keys = [node_key] if isinstance(node_key, str) else list(node_key)
    if not node_keys:
        raise ValueError("At least one node key is required.")
    selected_nodes: list[dict[str, Any]] = []
    for raw_key in node_keys:
        if ":" not in raw_key:
            raise ValueError(f"Unsupported node key '{raw_key}'. Expected '<prefix>:<entity_id>'.")
        prefix, entity_id = raw_key.split(":", 1)
        entity_id = entity_id.strip()
        if not entity_id:
            raise ValueError(f"Invalid node key '{raw_key}'. Missing entity id.")
        if prefix == "supplier":
            supplier_ids.append(entity_id)
            node_type = "supplier"
        elif prefix == "item":
            item_ids.append(entity_id)
            node_type = "item"
        else:
            raise ValueError(f"Unsupported node key prefix '{prefix}'.")
        selected_nodes.append(
            {
                "node_id": entity_id,
                "node_type": node_type,
                "selection_mode": "interactive_click",
            }
        )
    supplier_ids = sorted(set(supplier_ids))
    item_ids = sorted(set(item_ids))
    selected_ids = [node["node_id"] for node in selected_nodes]
    target_id = ",".join(selected_ids)

    description = (
        f"动态前端点击节点触发的定点中断情境：{target_id}，"
        f"基于{ '随机中断' if family == 'random' else '关键节点中断' }展示族生成。"
    )
    return ScenarioSpec(
        scenario_id=f"interactive_{family}_{len(selected_ids)}nodes_{selected_ids[0]}".lower(),
        scenario_type="random_distributed_node_disruption",
        target_type="node_group",
        target_id=target_id,
        start_date=pd.Timestamp(reference.start_date).normalize(),
        duration_days=int(reference.duration_days),
        severity=float(severity),
        description=description,
        extra={
            "scene_family": family,
            "target_supplier_ids": supplier_ids,
            "target_item_ids": item_ids,
            "selected_nodes": selected_nodes,
            "trigger_node_key": node_keys[0],
            "trigger_node_keys": node_keys,
            "reference_scene_id": reference.scenario_id,
        },
    )


def run_custom_node_experiment(
    *,
    model: ModelBundle,
    scenario: ScenarioSpec,
    output_dir: str | Path,
    policy_profile: str = "time_priority_interrupt",
    report_profile: str = "minimal",
    params_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from supply_disruption_sim.reporting.report_generator import generate_report

    params = _build_params(model=model, params_overrides=params_overrides)
    policies = build_policy_set(policy_profile=policy_profile)
    result = run_simulation(model=model, scenario=scenario, policies=policies, params=params)
    policy_comparison_summary, policy_comparison_time_series = build_policy_comparison_outputs_for_scenario(
        model=model,
        scenario=scenario,
        baseline_result=result,
        baseline_policy_profile=policy_profile,
        params=params,
    )
    artifacts = generate_report(
        result,
        output_dir,
        report_profile=report_profile,
        params=asdict(params),
        policy_comparison_summary=policy_comparison_summary,
        policy_comparison_time_series=policy_comparison_time_series,
    )
    return {
        "scenario": scenario,
        "params": params,
        "policies": policies,
        "result": result,
        "artifacts": artifacts,
        "policy_comparison_summary": policy_comparison_summary,
        "policy_comparison_time_series": policy_comparison_time_series,
    }


def _build_params(model: ModelBundle, params_overrides: dict[str, Any] | None) -> SimulationParams:
    params = load_default_params(model)
    if params_overrides:
        for key, value in params_overrides.items():
            if not hasattr(params, key):
                raise KeyError(f"Unknown simulation parameter override: {key}")
            setattr(params, key, value)
    params.mode = "bayesian"
    params.bayesian_enabled = True
    params.bayesian_use_sampling = bool(getattr(params, "bayesian_use_sampling", False))
    if isinstance(params.bayesian_config, dict):
        params.bayesian_config["use_sampling"] = params.bayesian_use_sampling
    return params
