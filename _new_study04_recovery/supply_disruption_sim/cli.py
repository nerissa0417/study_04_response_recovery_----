from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from supply_disruption_sim import export_standard_bundle, load_raw_bundle, standardize, validate_standard_bundle
from supply_disruption_sim.experiment.batch_runner import run_batch_experiments
from supply_disruption_sim.experiment.monte_carlo import run_monte_carlo_experiments
from supply_disruption_sim.experiment.runner import run_experiment
from supply_disruption_sim.experiment.sensitivity_runner import (
    DEFAULT_SENSITIVITY_PARAMETER_GRID,
    run_sensitivity_analysis,
)


MODE_CHOICES = ["deterministic", "bayesian"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Supply disruption simulation prototype")
    subparsers = parser.add_subparsers(dest="command", required=True)

    standardize_parser = subparsers.add_parser("standardize", help="Standardize input data and export reports")
    standardize_parser.add_argument("--input-dir", default="Input_data")
    standardize_parser.add_argument("--output-dir", default="output/standardized")

    run_parser = subparsers.add_parser("run", help="Run a disruption scenario")
    run_parser.add_argument("--input-dir", default="Input_data")
    run_parser.add_argument("--scenario", default="default_single_supplier_disruption")
    run_parser.add_argument("--output-dir", default="output/run_default")
    run_parser.add_argument("--policy-profile", default="baseline")
    run_parser.add_argument("--report-profile", choices=["minimal", "full", "paper"], default="minimal")
    run_parser.add_argument("--mode", choices=MODE_CHOICES, default=None)
    run_parser.add_argument("--bayesian-use-sampling", action=argparse.BooleanOptionalAction, default=None)
    run_parser.add_argument("--bayesian-random-seed", type=int, default=None)
    run_parser.add_argument("--standardized-output-dir", default=None)

    batch_parser = subparsers.add_parser("batch", help="Run a batch of scenarios and policy profiles")
    batch_parser.add_argument("--input-dir", default="Input_data")
    batch_parser.add_argument("--output-dir", default="output/batch_runs")
    batch_parser.add_argument(
        "--scenarios",
        nargs="+",
        default=["default_single_supplier_disruption", "default_region_disruption"],
    )
    batch_parser.add_argument(
        "--policy-profiles",
        nargs="+",
        default=[
            "baseline",
            "all_policies",
            "no_policy",
            "only_backup_switch",
            "only_substitution",
            "only_priority_repair",
        ],
    )
    batch_parser.add_argument("--report-profile", choices=["minimal", "full", "paper"], default="minimal")
    batch_parser.add_argument("--mode", choices=MODE_CHOICES, default=None)
    batch_parser.add_argument("--bayesian-use-sampling", action=argparse.BooleanOptionalAction, default=None)
    batch_parser.add_argument("--bayesian-random-seed", type=int, default=None)
    batch_parser.add_argument("--standardized-output-dir", default=None)

    sensitivity_parser = subparsers.add_parser("sensitivity", help="Run parameter sensitivity analysis")
    sensitivity_parser.add_argument("--input-dir", default="Input_data")
    sensitivity_parser.add_argument("--scenario", default="default_single_supplier_disruption")
    sensitivity_parser.add_argument("--output-dir", default="output/sensitivity_runs")
    sensitivity_parser.add_argument("--policy-profile", default="baseline")
    sensitivity_parser.add_argument(
        "--parameters",
        nargs="+",
        default=list(DEFAULT_SENSITIVITY_PARAMETER_GRID.keys()),
    )
    sensitivity_parser.add_argument("--random-seed", type=int, default=42)
    sensitivity_parser.add_argument("--mode", choices=MODE_CHOICES, default=None)
    sensitivity_parser.add_argument("--bayesian-use-sampling", action=argparse.BooleanOptionalAction, default=None)
    sensitivity_parser.add_argument("--bayesian-random-seed", type=int, default=None)
    sensitivity_parser.add_argument("--standardized-output-dir", default=None)

    monte_carlo_parser = subparsers.add_parser("monte-carlo", help="Run Monte Carlo robustness experiments")
    monte_carlo_parser.add_argument("--input-dir", default="Input_data")
    monte_carlo_parser.add_argument("--output-dir", default="output/monte_carlo_runs")
    monte_carlo_parser.add_argument(
        "--scenarios",
        nargs="+",
        default=["default_single_supplier_disruption"],
    )
    monte_carlo_parser.add_argument(
        "--policy-profiles",
        nargs="+",
        default=["baseline", "no_priority_repair"],
    )
    monte_carlo_parser.add_argument("--trials", type=int, default=20)
    monte_carlo_parser.add_argument("--random-seed", type=int, default=42)
    monte_carlo_parser.add_argument("--mode", choices=MODE_CHOICES, default=None)
    monte_carlo_parser.add_argument("--bayesian-use-sampling", action=argparse.BooleanOptionalAction, default=None)
    monte_carlo_parser.add_argument("--bayesian-random-seed", type=int, default=None)
    monte_carlo_parser.add_argument("--standardized-output-dir", default=None)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "standardize":
        run_standardize(Path(args.input_dir), Path(args.output_dir))
        return
    if args.command == "run":
        run_scenario(
            Path(args.input_dir),
            args.scenario,
            Path(args.output_dir),
            policy_profile=args.policy_profile,
            report_profile=args.report_profile,
            mode=args.mode,
            bayesian_use_sampling=args.bayesian_use_sampling,
            bayesian_random_seed=args.bayesian_random_seed,
            standardized_output_dir=args.standardized_output_dir,
        )
        return
    if args.command == "batch":
        run_batch(
            Path(args.input_dir),
            args.scenarios,
            Path(args.output_dir),
            policy_profiles=args.policy_profiles,
            report_profile=args.report_profile,
            mode=args.mode,
            bayesian_use_sampling=args.bayesian_use_sampling,
            bayesian_random_seed=args.bayesian_random_seed,
            standardized_output_dir=args.standardized_output_dir,
        )
        return
    if args.command == "sensitivity":
        run_sensitivity(
            Path(args.input_dir),
            args.scenario,
            Path(args.output_dir),
            policy_profile=args.policy_profile,
            parameters=args.parameters,
            random_seed=args.random_seed,
            mode=args.mode,
            bayesian_use_sampling=args.bayesian_use_sampling,
            bayesian_random_seed=args.bayesian_random_seed,
            standardized_output_dir=args.standardized_output_dir,
        )
        return
    if args.command == "monte-carlo":
        run_monte_carlo(
            Path(args.input_dir),
            args.scenarios,
            Path(args.output_dir),
            policy_profiles=args.policy_profiles,
            trials=args.trials,
            random_seed=args.random_seed,
            mode=args.mode,
            bayesian_use_sampling=args.bayesian_use_sampling,
            bayesian_random_seed=args.bayesian_random_seed,
            standardized_output_dir=args.standardized_output_dir,
        )
        return
    raise ValueError(f"Unsupported command: {args.command}")


def run_standardize(input_dir: Path, output_dir: Path) -> dict:
    raw_bundle = load_raw_bundle(input_dir)
    standard_bundle = standardize(raw_bundle)
    report = validate_standard_bundle(standard_bundle)
    export_standard_bundle(standard_bundle, output_dir)
    validation_path = output_dir / "validation_report.json"
    payload = {
        "is_valid": report.is_valid,
        "validation_report": str(validation_path),
        "issues": [
            {
                "level": issue.level,
                "check": issue.check,
                "message": issue.message,
                "details": issue.details,
            }
            for issue in report.issues
        ],
    }
    validation_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return payload


def run_scenario(
    input_dir: Path,
    scenario_name: str,
    output_dir: Path,
    policy_profile: str = "baseline",
    report_profile: str = "minimal",
    mode: str | None = None,
    bayesian_use_sampling: bool | None = None,
    bayesian_random_seed: int | None = None,
    standardized_output_dir: str | Path | None = None,
) -> dict:
    return run_experiment(
        input_dir=input_dir,
        scenario_name=scenario_name,
        output_dir=output_dir,
        policy_profile=policy_profile,
        report_profile=report_profile,
        params_overrides=_build_params_overrides(
            mode=mode,
            bayesian_use_sampling=bayesian_use_sampling,
            bayesian_random_seed=bayesian_random_seed,
        ),
        standardized_output_dir=standardized_output_dir,
    )


def run_batch(
    input_dir: Path,
    scenarios: list[str],
    output_dir: Path,
    policy_profiles: list[str] | None = None,
    report_profile: str = "minimal",
    mode: str | None = None,
    bayesian_use_sampling: bool | None = None,
    bayesian_random_seed: int | None = None,
    standardized_output_dir: str | Path | None = None,
) -> dict:
    return run_batch_experiments(
        input_dir=input_dir,
        scenarios=scenarios,
        output_dir=output_dir,
        policy_profiles=policy_profiles,
        report_profile=report_profile,
        params_overrides=_build_params_overrides(
            mode=mode,
            bayesian_use_sampling=bayesian_use_sampling,
            bayesian_random_seed=bayesian_random_seed,
        ),
        standardized_output_dir=standardized_output_dir,
    )


def run_sensitivity(
    input_dir: Path,
    scenario_name: str,
    output_dir: Path,
    policy_profile: str = "baseline",
    parameters: list[str] | None = None,
    random_seed: int = 42,
    mode: str | None = None,
    bayesian_use_sampling: bool | None = None,
    bayesian_random_seed: int | None = None,
    standardized_output_dir: str | Path | None = None,
) -> dict:
    parameter_grid = {
        name: DEFAULT_SENSITIVITY_PARAMETER_GRID[name]
        for name in (parameters or list(DEFAULT_SENSITIVITY_PARAMETER_GRID))
        if name in DEFAULT_SENSITIVITY_PARAMETER_GRID
    }
    return run_sensitivity_analysis(
        input_dir=input_dir,
        scenario_name=scenario_name,
        output_dir=output_dir,
        policy_profile=policy_profile,
        parameter_grid=parameter_grid,
        random_seed=random_seed,
        params_overrides=_build_params_overrides(
            mode=mode,
            bayesian_use_sampling=bayesian_use_sampling,
            bayesian_random_seed=bayesian_random_seed,
        ),
        standardized_output_dir=standardized_output_dir,
    )


def run_monte_carlo(
    input_dir: Path,
    scenarios: list[str],
    output_dir: Path,
    policy_profiles: list[str] | None = None,
    trials: int = 20,
    random_seed: int = 42,
    mode: str | None = None,
    bayesian_use_sampling: bool | None = None,
    bayesian_random_seed: int | None = None,
    standardized_output_dir: str | Path | None = None,
) -> dict:
    return run_monte_carlo_experiments(
        input_dir=input_dir,
        scenarios=scenarios,
        output_dir=output_dir,
        policy_profiles=policy_profiles,
        trials=trials,
        random_seed=random_seed,
        params_overrides=_build_params_overrides(
            mode=mode,
            bayesian_use_sampling=bayesian_use_sampling,
            bayesian_random_seed=bayesian_random_seed,
        ),
        standardized_output_dir=standardized_output_dir,
    )


def _build_params_overrides(
    *,
    mode: str | None,
    bayesian_use_sampling: bool | None,
    bayesian_random_seed: int | None,
) -> dict[str, Any] | None:
    overrides: dict[str, Any] = {}
    if mode is not None:
        normalized_mode = str(mode).strip().lower()
        if normalized_mode not in MODE_CHOICES:
            raise ValueError(f"Unsupported mode: {mode}")
        overrides["mode"] = normalized_mode
        overrides["bayesian_enabled"] = normalized_mode == "bayesian"
        if normalized_mode != "bayesian":
            overrides["bayesian_use_sampling"] = False
    if bayesian_use_sampling is not None and overrides.get("mode", mode) != "deterministic":
        overrides["bayesian_use_sampling"] = bool(bayesian_use_sampling)
    if bayesian_random_seed is not None:
        overrides["bayesian_random_seed"] = int(bayesian_random_seed)
    return overrides or None


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "standardize":
        print(
            json.dumps(
                run_standardize(Path(args.input_dir), Path(args.output_dir)),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    elif args.command == "run":
        print(
            json.dumps(
                run_scenario(
                    Path(args.input_dir),
                    args.scenario,
                    Path(args.output_dir),
                    policy_profile=args.policy_profile,
                    report_profile=args.report_profile,
                    mode=args.mode,
                    bayesian_use_sampling=args.bayesian_use_sampling,
                    bayesian_random_seed=args.bayesian_random_seed,
                    standardized_output_dir=args.standardized_output_dir,
                ),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    elif args.command == "batch":
        print(
            json.dumps(
                run_batch(
                    Path(args.input_dir),
                    args.scenarios,
                    Path(args.output_dir),
                    policy_profiles=args.policy_profiles,
                    report_profile=args.report_profile,
                    mode=args.mode,
                    bayesian_use_sampling=args.bayesian_use_sampling,
                    bayesian_random_seed=args.bayesian_random_seed,
                    standardized_output_dir=args.standardized_output_dir,
                ),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    elif args.command == "sensitivity":
        print(
            json.dumps(
                run_sensitivity(
                    Path(args.input_dir),
                    args.scenario,
                    Path(args.output_dir),
                    policy_profile=args.policy_profile,
                    parameters=args.parameters,
                    random_seed=args.random_seed,
                    mode=args.mode,
                    bayesian_use_sampling=args.bayesian_use_sampling,
                    bayesian_random_seed=args.bayesian_random_seed,
                    standardized_output_dir=args.standardized_output_dir,
                ),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    elif args.command == "monte-carlo":
        print(
            json.dumps(
                run_monte_carlo(
                    Path(args.input_dir),
                    args.scenarios,
                    Path(args.output_dir),
                    policy_profiles=args.policy_profiles,
                    trials=args.trials,
                    random_seed=args.random_seed,
                    mode=args.mode,
                    bayesian_use_sampling=args.bayesian_use_sampling,
                    bayesian_random_seed=args.bayesian_random_seed,
                    standardized_output_dir=args.standardized_output_dir,
                ),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
