from __future__ import annotations

import json
from pathlib import Path

import yaml

from supply_disruption_sim.cli import run_batch, run_monte_carlo, run_scenario, run_sensitivity, run_standardize


CONFIG_PATH = Path(__file__).resolve().parent / "supply_disruption_sim" / "config" / "run_config.yaml"


def load_run_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    run_config = load_run_config()
    input_dir = Path(run_config["input_dir"])
    standardize_cfg = run_config.get("standardize", {})
    simulation_cfg = run_config.get("simulation", {})
    batch_cfg = run_config.get("batch", {})
    sensitivity_cfg = run_config.get("sensitivity", {})
    monte_carlo_cfg = run_config.get("monte_carlo", {})
    standardized_output_dir = (
        Path(standardize_cfg["output_dir"]) if standardize_cfg.get("enabled", False) else None
    )

    if standardize_cfg.get("enabled", False) and not simulation_cfg.get("enabled", False) and not batch_cfg.get("enabled", False):
        standardize_result = run_standardize(
            input_dir=input_dir,
            output_dir=Path(standardize_cfg["output_dir"]),
        )
        print("=== STANDARDIZE RESULT ===")
        print(json.dumps(standardize_result, ensure_ascii=False, indent=2, default=str))

    if simulation_cfg.get("enabled", False):
        simulation_result = run_scenario(
            input_dir=input_dir,
            scenario_name=simulation_cfg["scenario"],
            output_dir=Path(simulation_cfg["output_dir"]),
            policy_profile=str(simulation_cfg.get("policy_profile", "baseline")),
            report_profile=str(simulation_cfg.get("report_profile", "minimal")),
            mode=_optional_mode(simulation_cfg),
            bayesian_use_sampling=_optional_bool(simulation_cfg, "bayesian_use_sampling"),
            bayesian_random_seed=_optional_int(simulation_cfg, "bayesian_random_seed"),
            standardized_output_dir=standardized_output_dir,
        )
        print("=== SIMULATION RESULT ===")
        print(json.dumps(simulation_result, ensure_ascii=False, indent=2, default=str))

    if batch_cfg.get("enabled", False):
        batch_result = run_batch(
            input_dir=input_dir,
            scenarios=list(batch_cfg.get("scenarios", [])),
            output_dir=Path(batch_cfg["output_dir"]),
            policy_profiles=list(batch_cfg.get("policy_profiles", [])) or None,
            report_profile=str(batch_cfg.get("report_profile", "minimal")),
            mode=_optional_mode(batch_cfg),
            bayesian_use_sampling=_optional_bool(batch_cfg, "bayesian_use_sampling"),
            bayesian_random_seed=_optional_int(batch_cfg, "bayesian_random_seed"),
            standardized_output_dir=standardized_output_dir,
        )
        print("=== BATCH RESULT ===")
        print(json.dumps(batch_result, ensure_ascii=False, indent=2, default=str))

    if sensitivity_cfg.get("enabled", False):
        sensitivity_result = run_sensitivity(
            input_dir=input_dir,
            scenario_name=str(sensitivity_cfg.get("scenario", "default_single_supplier_disruption")),
            output_dir=Path(sensitivity_cfg["output_dir"]),
            policy_profile=str(sensitivity_cfg.get("policy_profile", "baseline")),
            parameters=list(sensitivity_cfg.get("parameters", [])) or None,
            random_seed=int(sensitivity_cfg.get("random_seed", 42)),
            mode=_optional_mode(sensitivity_cfg),
            bayesian_use_sampling=_optional_bool(sensitivity_cfg, "bayesian_use_sampling"),
            bayesian_random_seed=_optional_int(sensitivity_cfg, "bayesian_random_seed"),
            standardized_output_dir=standardized_output_dir,
        )
        print("=== SENSITIVITY RESULT ===")
        print(json.dumps(sensitivity_result, ensure_ascii=False, indent=2, default=str))

    if monte_carlo_cfg.get("enabled", False):
        monte_carlo_result = run_monte_carlo(
            input_dir=input_dir,
            scenarios=list(monte_carlo_cfg.get("scenarios", [])),
            output_dir=Path(monte_carlo_cfg["output_dir"]),
            policy_profiles=list(monte_carlo_cfg.get("policy_profiles", [])) or None,
            trials=int(monte_carlo_cfg.get("trials", 20)),
            random_seed=int(monte_carlo_cfg.get("random_seed", 42)),
            mode=_optional_mode(monte_carlo_cfg),
            bayesian_use_sampling=_optional_bool(monte_carlo_cfg, "bayesian_use_sampling"),
            bayesian_random_seed=_optional_int(monte_carlo_cfg, "bayesian_random_seed"),
            standardized_output_dir=standardized_output_dir,
        )
        print("=== MONTE CARLO RESULT ===")
        print(json.dumps(monte_carlo_result, ensure_ascii=False, indent=2, default=str))


def _optional_mode(section: dict) -> str | None:
    value = section.get("mode")
    return str(value).strip().lower() if value is not None else None


def _optional_bool(section: dict, key: str) -> bool | None:
    return bool(section[key]) if key in section else None


def _optional_int(section: dict, key: str) -> int | None:
    return int(section[key]) if key in section and section[key] is not None else None


if __name__ == "__main__":
    main()
