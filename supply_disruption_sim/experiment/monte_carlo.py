from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import matplotlib
import pandas as pd


matplotlib.use("Agg")

import matplotlib.pyplot as plt

from supply_disruption_sim.labels import policy_profile_label, scenario_label
from supply_disruption_sim.experiment.runner import prepare_experiment_context
from supply_disruption_sim.experiment.sensitivity_runner import prepare_variant_inputs
from supply_disruption_sim.disruption.recovery_engine import run_simulation


DEFAULT_MONTE_CARLO_DISTRIBUTIONS: dict[str, dict[str, Any]] = {
    "single_source_ratio": {"dist": "uniform", "low": 0.75, "high": 1.0},
    "backup_coverage": {"dist": "uniform", "low": 0.0, "high": 1.0},
    "substitution_availability": {"dist": "uniform", "low": 0.0, "high": 1.0},
    "backup_switch_time_days": {"dist": "randint", "low": 3, "high": 14},
    "priority_repair_lead_days": {"dist": "randint", "low": 2, "high": 8},
    "incident_duration_factor": {"dist": "choice", "values": [0.75, 1.0, 1.25, 1.5], "weights": [1, 2, 2, 1]},
}

DEFAULT_MONTE_CARLO_METRICS = [
    "average_service_level",
    "ttr_days",
    "estimated_disruption_loss",
    "policy_total_cost",
]


def run_monte_carlo_experiments(
    input_dir: str | Path,
    scenarios: list[str],
    output_dir: str | Path,
    policy_profiles: list[str] | None = None,
    trials: int = 20,
    standardized_output_dir: str | Path | None = None,
    random_seed: int = 42,
    parameter_distributions: dict[str, dict[str, Any]] | None = None,
    params_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_path = Path(output_dir)
    tables_dir = output_path / "tables"
    figures_dir = output_path / "figures"
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    context = prepare_experiment_context(
        input_dir=input_dir,
        standardized_output_dir=standardized_output_dir,
    )
    base_model = context["model"]
    rng = random.Random(random_seed)
    selected_profiles = policy_profiles or ["time_priority_interrupt", "no_priority_repair"]
    distributions = parameter_distributions or dict(DEFAULT_MONTE_CARLO_DISTRIBUTIONS)

    records: list[dict[str, Any]] = []
    for scenario_name in scenarios:
        for policy_profile in selected_profiles:
            for trial_index in range(int(trials)):
                sampled_parameters = _sample_parameters(distributions, rng)
                variant_model, scenario, params, policies, applied_parameters = prepare_variant_inputs(
                    base_model=base_model,
                    scenario_name=scenario_name,
                    policy_profile=policy_profile,
                    parameter_values=sampled_parameters,
                    random_seed=random_seed + trial_index,
                    params_overrides=params_overrides,
                )
                result = run_simulation(
                    model=variant_model,
                    scenario=scenario,
                    policies=policies,
                    params=params,
                )
                record = {
                    "scenario_name": scenario_name,
                    "scenario_id": result.scenario.scenario_id,
                    "policy_profile": policy_profile,
                    "trial_id": trial_index,
                }
                for parameter_name, value in applied_parameters.items():
                    record[parameter_name] = value
                record.update(result.summary)
                records.append(record)

    samples_df = pd.DataFrame(records)
    robustness_df = _build_robustness_summary(samples_df)

    samples_csv = tables_dir / "monte_carlo_samples.csv"
    robustness_csv = tables_dir / "robustness_summary.csv"
    robustness_figure = figures_dir / "robustness_comparison.png"

    samples_df.to_csv(samples_csv, index=False)
    robustness_df.to_csv(robustness_csv, index=False)
    _plot_robustness_comparison(robustness_df, robustness_figure)
    return {
        "output_dir": str(output_path),
        "standardized_paths": context["standardized_paths"],
        "validation_report": context["validation_report"],
        "samples_csv": str(samples_csv),
        "robustness_csv": str(robustness_csv),
        "robustness_figure": str(robustness_figure),
    }


def _sample_parameters(distributions: dict[str, dict[str, Any]], rng: random.Random) -> dict[str, float | int]:
    sampled: dict[str, float | int] = {}
    for parameter_name, spec in distributions.items():
        distribution = str(spec.get("dist", "uniform"))
        if distribution == "uniform":
            low = float(spec["low"])
            high = float(spec["high"])
            sampled[parameter_name] = round(rng.uniform(low, high), 4)
            continue
        if distribution == "randint":
            low = int(spec["low"])
            high = int(spec["high"])
            sampled[parameter_name] = rng.randint(low, high)
            continue
        if distribution == "choice":
            values = list(spec.get("values", []))
            weights = list(spec.get("weights", [])) or None
            sampled[parameter_name] = rng.choices(values, weights=weights, k=1)[0]
            continue
        raise ValueError(f"Unsupported Monte Carlo distribution: {distribution}")
    return sampled


def _build_robustness_summary(samples_df: pd.DataFrame) -> pd.DataFrame:
    if samples_df.empty:
        return pd.DataFrame()
    group_cols = ["scenario_id", "policy_profile"]
    records: list[dict[str, Any]] = []
    for group_key, group in samples_df.groupby(group_cols, dropna=False):
        scenario_id, policy_profile = group_key
        record: dict[str, Any] = {
            "scenario_id": scenario_id,
            "policy_profile": policy_profile,
            "trial_count": int(len(group)),
        }
        for metric in DEFAULT_MONTE_CARLO_METRICS:
            if metric not in group.columns:
                continue
            series = pd.to_numeric(group[metric], errors="coerce").dropna()
            if series.empty:
                continue
            record[f"{metric}_mean"] = round(float(series.mean()), 4)
            record[f"{metric}_std"] = round(float(series.std(ddof=0)), 4)
            record[f"{metric}_p05"] = round(float(series.quantile(0.05)), 4)
            record[f"{metric}_p50"] = round(float(series.quantile(0.5)), 4)
            record[f"{metric}_p95"] = round(float(series.quantile(0.95)), 4)
        if "average_service_level" in group.columns:
            record["service_level_target_hit_rate"] = round(
                float((group["average_service_level"] >= 0.95).mean()),
                4,
            )
        if "ttr_days" in group.columns:
            valid_ttr = pd.to_numeric(group["ttr_days"], errors="coerce")
            record["recovery_within_10_days_rate"] = round(float((valid_ttr <= 10).fillna(False).mean()), 4)
        records.append(record)
    return pd.DataFrame(records).sort_values(by=["scenario_id", "policy_profile"]).reset_index(drop=True)

def _plot_robustness_comparison(robustness_df: pd.DataFrame, figure_path: Path) -> None:
    if robustness_df.empty:
        return
    metrics = [
        ("average_service_level_mean", "平均服务水平"),
        ("ttr_days_p95", "恢复时间 P95"),
        ("estimated_disruption_loss_mean", "平均中断损失"),
        ("service_level_target_hit_rate", "服务水平达标率"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(13.2, 8.2))
    labels = robustness_df.apply(
        lambda row: f"{scenario_label(str(row['scenario_id']))}\n{policy_profile_label(str(row['policy_profile']))}",
        axis=1,
    )
    for ax, (metric, title) in zip(axes.flat, metrics):
        if metric not in robustness_df.columns:
            ax.set_axis_off()
            continue
        ax.bar(labels, robustness_df[metric], color="#2A6F97", alpha=0.92, edgecolor="#FFFFFF", linewidth=0.9)
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=18)
        ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
