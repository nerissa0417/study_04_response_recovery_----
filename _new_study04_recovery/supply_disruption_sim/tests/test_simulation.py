from __future__ import annotations

import unittest
from pathlib import Path
import tempfile
import copy
import shutil
import re
import json

import pandas as pd

from supply_disruption_sim.data_adapter.raw_loader import load_raw_bundle
from supply_disruption_sim.data_adapter.standardizer import standardize
from supply_disruption_sim.data_adapter.validator import validate_standard_bundle
from supply_disruption_sim.disruption.scenario_loader import (
    load_default_params,
    load_default_policies,
    load_scenario,
)
from supply_disruption_sim.disruption.recovery_engine import run_simulation
from supply_disruption_sim.disruption.scenario_injector import inject_scenario_for_day
from supply_disruption_sim.experiment.batch_runner import run_batch_experiments
from supply_disruption_sim.experiment.monte_carlo import run_monte_carlo_experiments
from supply_disruption_sim.experiment.runner import build_policy_set, run_experiment
from supply_disruption_sim.experiment.sensitivity_runner import run_sensitivity_analysis
from supply_disruption_sim.model.builder import build_model
from supply_disruption_sim.model.state_model import initialize_state
from supply_disruption_sim.reporting.report_generator import generate_report
from supply_disruption_sim.viz.graph_export import build_export_graph
from supply_disruption_sim.types import ScenarioSpec


ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = ROOT / "Input_data"


class SimulationPipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw_bundle = load_raw_bundle(INPUT_DIR)
        cls.standard_bundle = standardize(cls.raw_bundle)
        cls.validation_report = validate_standard_bundle(cls.standard_bundle)
        cls.model = build_model(cls.standard_bundle)

    def test_standardized_bundle_is_valid(self) -> None:
        self.assertTrue(self.validation_report.is_valid)

    def test_final_product_is_mid0006(self) -> None:
        final_products = self.standard_bundle.metadata["final_product_ids"]
        self.assertEqual(final_products, ["MID0006"])

    def test_augmented_backup_cases_exist(self) -> None:
        augmented_items = self.standard_bundle.metadata["augmented_backup_items"]
        self.assertGreaterEqual(len(augmented_items), 3)

    def test_mid0019_has_backup_supplier(self) -> None:
        rows = self.standard_bundle.supplier_item_map
        target = rows.loc[(rows["item_id"] == "MID0019") & (rows["is_backup"])]
        self.assertFalse(target.empty)

    def test_mid0014_has_equivalent_materials(self) -> None:
        alts = self.standard_bundle.part_alternatives
        target = alts.loc[alts["item_id"] == "MID0014", "alt_item_id"].tolist()
        self.assertEqual(target, ["MID0009", "MID0019"])

    def test_default_scenario_runs(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        policies = load_default_policies()
        result = run_simulation(self.model, scenario, policies, params)
        self.assertFalse(result.history.empty)
        self.assertIn("final_product_status", result.history.columns)
        self.assertIn("supply_degraded_items", result.history.columns)
        self.assertIn(result.history["final_product_status"].iloc[0], {"active", "affected", "failed"})
        self.assertTrue(any(path["impact_dimension"] == "supply" for path in result.impacted_paths))

    def test_historical_scenario_runs(self) -> None:
        incident_id = self.standard_bundle.incident_events.iloc[0]["incident_id"]
        scenario = load_scenario(f"historical:{incident_id}", self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), load_default_params(self.model))
        self.assertEqual(result.scenario.target_type, "supplier")
        self.assertGreaterEqual(len(result.history), 30)

    def test_stage1_state_containers_exist(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        state = initialize_state(self.model, scenario, params)
        self.assertIn("suppliers", state.supply_state)
        self.assertIn("items", state.demand_state)
        self.assertIn("products", state.fused_state)
        self.assertTrue(state.node_state)
        self.assertTrue(state.edge_state)

    def test_stage2_supply_item_history_fields_exist(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), params)
        self.assertIn("item_level", result.item_history.columns)
        self.assertIn("supply_effective_status", result.item_history.columns)
        self.assertIn("assembly_status", result.item_history.columns)

    def test_stage3_demand_fields_exist(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), params)
        self.assertIn("total_requested_demand", result.history.columns)
        self.assertIn("total_backlog_demand", result.history.columns)
        self.assertIn("demand_fulfillment_rate", result.history.columns)
        self.assertIn("requested_demand", result.item_history.columns)
        self.assertIn("fulfilled_demand", result.item_history.columns)
        self.assertIn("backlog_demand", result.item_history.columns)
        self.assertIn("lost_demand", result.item_history.columns)
        self.assertIn("demand_status", result.item_history.columns)
        self.assertTrue(any(path["impact_dimension"] == "demand" for path in result.impacted_paths))

    def test_stage4_fusion_fields_exist(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), params)
        self.assertIn("fused_affected_items", result.history.columns)
        self.assertIn("fused_failed_items", result.history.columns)
        self.assertIn("system_service_level", result.history.columns)
        self.assertIn("system_root_cause", result.history.columns)
        self.assertIn("fused_status", result.item_history.columns)
        self.assertIn("fused_root_cause", result.item_history.columns)
        self.assertIn("avg_system_service_level", result.summary)
        self.assertTrue(any(path["impact_dimension"] == "fusion" for path in result.impacted_paths))

    def test_stage5_network_snapshots_export(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), params)
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = generate_report(result, tmp_dir)
            self.assertEqual(len(artifacts.network_snapshot_paths), 4)
            for path in artifacts.network_snapshot_paths:
                self.assertTrue(path.exists())

    def test_stage5_network_layout_places_items_above_suppliers(self) -> None:
        graph, positions = build_export_graph(self.model)
        supplier_y = [y for node_key, (_, y) in positions.items() if node_key.startswith("supplier:")]
        item_y = [y for node_key, (_, y) in positions.items() if node_key.startswith("item:")]
        self.assertTrue(supplier_y)
        self.assertTrue(item_y)
        self.assertLess(max(supplier_y), min(item_y))

    def test_stage5_network_layout_orders_bom_from_left_to_right(self) -> None:
        _, positions = build_export_graph(self.model)
        items = self.standard_bundle.items.set_index("item_id")
        level_positions: dict[str, list[float]] = {"material": [], "part": [], "assembly": [], "product": []}
        for item_id, row in items.iterrows():
            item_level = str(row["item_level"])
            if item_level not in level_positions:
                continue
            x_coord, _ = positions[f"item:{item_id}"]
            level_positions[item_level].append(float(x_coord))
        self.assertLess(
            sum(level_positions["material"]) / len(level_positions["material"]),
            sum(level_positions["part"]) / len(level_positions["part"]),
        )
        self.assertLess(
            sum(level_positions["part"]) / len(level_positions["part"]),
            sum(level_positions["assembly"]) / len(level_positions["assembly"]),
        )
        self.assertLess(
            sum(level_positions["assembly"]) / len(level_positions["assembly"]),
            sum(level_positions["product"]) / len(level_positions["product"]),
        )

    def test_stage5_visual_mapping_edges_only_target_parts_and_materials(self) -> None:
        graph, _ = build_export_graph(self.model)
        for _, target, data in graph.edges(data=True):
            if not str(data.get("edge_key", "")).startswith("supply_edge:"):
                continue
            self.assertTrue(target.startswith("item:"))
            item_level = graph.nodes[target].get("item_level")
            self.assertIn(item_level, {"part", "material"})

    def test_stage6_region_scenario_runs(self) -> None:
        scenario = load_scenario("default_region_disruption", self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), load_default_params(self.model))
        self.assertEqual(scenario.target_type, "region")
        self.assertGreater(result.history["disrupted_suppliers"].max(), 0)

    def test_stage6_material_shortage_runs(self) -> None:
        scenario = load_scenario("default_material_shortage", self.model)
        self.assertEqual(scenario.target_type, "material")
        context = inject_scenario_for_day(
            current_date=scenario.start_date.normalize(),
            scenario=scenario,
            model=self.model,
        )
        self.assertIn(scenario.target_id, context["material_shortages"])

    def test_stage6_priority_repair_improves_recovery(self) -> None:
        scenario = ScenarioSpec(
            scenario_id="priority_repair_compare",
            scenario_type="single_supplier_disruption",
            target_type="supplier",
            target_id=self.standard_bundle.metadata["default_disruption_supplier_id"],
            start_date=pd.Timestamp("2025-06-15"),
            duration_days=30,
            severity=1.0,
        )
        params = load_default_params(self.model)
        with_priority = load_default_policies()
        without_priority = copy.deepcopy(with_priority)
        for policy in without_priority:
            if policy.policy_type == "priority_repair":
                policy.enabled = False
        result_with = run_simulation(self.model, scenario, with_priority, params)
        result_without = run_simulation(self.model, scenario, without_priority, params)

        def normalize_ttr(value):
            return 10**9 if value is None else value

        self.assertLessEqual(
            normalize_ttr(result_with.summary["ttr_days"]),
            normalize_ttr(result_without.summary["ttr_days"]),
        )

    def test_gap02_multi_supplier_scenario_runs(self) -> None:
        scenario = load_scenario("default_multi_supplier_disruption", self.model)
        self.assertEqual(scenario.target_type, "supplier_group")
        self.assertGreaterEqual(len(scenario.extra.get("target_supplier_ids", [])), 2)
        result = run_simulation(self.model, scenario, load_default_policies(), load_default_params(self.model))
        self.assertGreaterEqual(int(result.history["disrupted_suppliers"].max()), 2)

    def test_gap02_supply_edge_disruption_runs(self) -> None:
        scenario = load_scenario("default_supply_edge_disruption", self.model)
        self.assertEqual(scenario.target_type, "supply_edge")
        context = inject_scenario_for_day(
            current_date=scenario.start_date.normalize(),
            scenario=scenario,
            model=self.model,
        )
        target = scenario.extra["supply_edge_target"]
        self.assertIn((target["supplier_id"], target["item_id"]), context["disrupted_supply_edges"])
        result = run_simulation(self.model, scenario, load_default_policies(), load_default_params(self.model))
        impacted_rows = result.item_history.loc[
            result.item_history["item_id"] == target["item_id"],
            "supply_effective_status",
        ]
        self.assertTrue(any(status in {"degraded", "unavailable"} for status in impacted_rows.tolist()))

    def test_gap02_progressive_supplier_scenario_runs(self) -> None:
        scenario = load_scenario("default_progressive_supplier_disruption", self.model)
        start_day = scenario.start_date.normalize()
        early_context = inject_scenario_for_day(start_day, scenario, self.model)
        peak_context = inject_scenario_for_day(start_day + pd.Timedelta(days=4), scenario, self.model)
        recovery_context = inject_scenario_for_day(start_day + pd.Timedelta(days=10), scenario, self.model)
        self.assertIn(scenario.target_id, early_context["degraded_suppliers"])
        self.assertIn(scenario.target_id, peak_context["disrupted_suppliers"])
        self.assertIn(scenario.target_id, recovery_context["degraded_suppliers"])
        result = run_simulation(self.model, scenario, load_default_policies(), load_default_params(self.model))
        self.assertGreater(result.history["degraded_suppliers"].max(), 0)
        self.assertGreater(result.history["disrupted_suppliers"].max(), 0)

    def test_stage7_single_experiment_report_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = run_experiment(
                input_dir=INPUT_DIR,
                scenario_name="default_single_supplier_disruption",
                output_dir=Path(tmp_dir) / "run",
                standardized_output_dir=Path(tmp_dir) / "standardized",
            )
            artifacts = payload["artifacts"]
            self.assertTrue(Path(artifacts["history_csv"]).exists())
            self.assertIsNone(artifacts["item_history_csv"])
            self.assertTrue(Path(artifacts["policy_events_csv"]).exists())
            self.assertTrue(Path(artifacts["summary_csv"]).exists())
            self.assertIsNone(artifacts["supply_history_csv"])
            self.assertIsNone(artifacts["demand_history_csv"])
            self.assertIsNone(artifacts["fusion_history_csv"])
            self.assertTrue(Path(artifacts["network_history_csv"]).exists())
            self.assertTrue(Path(artifacts["impacted_paths_csv"]).exists())
            self.assertTrue(Path(artifacts["summary_json"]).exists())
            self.assertTrue(Path(artifacts["figure_path"]).exists())
            self.assertIsNone(artifacts["impact_figure_path"])
            self.assertTrue(Path(artifacts["bom_figure_path"]).exists())
            self.assertIsNone(artifacts["timeline_figure_path"])
            self.assertTrue(Path(artifacts["monthly_disrupted_nodes_figure_path"]).exists())
            self.assertTrue(Path(artifacts["propagation_duration_figure_path"]).exists())
            self.assertTrue(Path(artifacts["core_trends_figure_path"]).exists())
            self.assertTrue(Path(artifacts["supplier_network_figure_path"]).exists())
            self.assertTrue(Path(artifacts["material_network_figure_path"]).exists())
            self.assertTrue(Path(artifacts["dashboard_data_json"]).exists())
            self.assertGreaterEqual(len(payload["artifacts"]["network_snapshot_paths"]), 4)
            summary_payload = json.loads(Path(artifacts["summary_json"]).read_text(encoding="utf-8"))
            self.assertEqual(summary_payload["report_profile"], "minimal")
            self.assertIn("network_history_csv", summary_payload["artifacts"])
            self.assertIn("monthly_disrupted_nodes_figure", summary_payload["artifacts"])
            self.assertIn("propagation_duration_figure", summary_payload["artifacts"])
            self.assertIn("core_metric_trends_figure", summary_payload["artifacts"])
            self.assertIn("supplier_network_trends_figure", summary_payload["artifacts"])
            self.assertIn("material_network_trends_figure", summary_payload["artifacts"])
            self.assertNotIn("item_history_csv", summary_payload["artifacts"])
            self.assertNotIn("impact_figure", summary_payload["artifacts"])
            self.assertNotIn("timeline_figure", summary_payload["artifacts"])

    def test_stage7_batch_runner_exports_comparison_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = run_batch_experiments(
                input_dir=INPUT_DIR,
                scenarios=["default_single_supplier_disruption", "default_region_disruption"],
                output_dir=Path(tmp_dir) / "batch",
                policy_profiles=["baseline", "no_priority_repair"],
                standardized_output_dir=Path(tmp_dir) / "standardized",
            )
            self.assertEqual(len(payload["runs"]), 4)
            self.assertTrue(Path(payload["summary_csv"]).exists())
            self.assertTrue(Path(payload["summary_json"]).exists())
            self.assertTrue(Path(payload["policy_summary_csv"]).exists())
            self.assertTrue(Path(payload["scenario_summary_csv"]).exists())
            self.assertTrue(Path(payload["network_comparison_csv"]).exists())
            self.assertIsNone(payload["comparison_figure_path"])
            self.assertIsNone(payload["scenario_figure_path"])
            self.assertTrue(Path(payload["timeline_comparison_figure_path"]).exists())
            self.assertTrue(Path(payload["supplier_network_comparison_figure_path"]).exists())
            self.assertTrue(Path(payload["material_network_comparison_figure_path"]).exists())
            self.assertTrue(Path(payload["monthly_disrupted_nodes_comparison_figure_path"]).exists())
            self.assertTrue(Path(payload["propagation_duration_comparison_figure_path"]).exists())
            self.assertIsNone(payload["paper_scenario_policy_csv"])
            self.assertIsNone(payload["paper_policy_effect_csv"])
            self.assertIsNone(payload["paper_policy_ranking_csv"])
            self.assertIsNone(payload["paper_parameter_dimension_csv"])
            self.assertTrue(Path(payload["paper_tradeoff_figure_path"]).exists())
            self.assertIsNone(payload["paper_summary_figure_path"])
            summary_df = pd.read_csv(payload["summary_csv"])
            network_comparison_df = pd.read_csv(payload["network_comparison_csv"])
            self.assertIn("policy_total_cost", summary_df.columns)
            self.assertIn("benefit_vs_reference", summary_df.columns)
            self.assertIn("day_offset", network_comparison_df.columns)
            self.assertIn("run_label", network_comparison_df.columns)
            self.assertIn("assembly_blocked_nodes", network_comparison_df.columns)
            self.assertIn("product_blocked_nodes", network_comparison_df.columns)

    def test_gap03_policy_cost_summary_and_events_exist(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), load_default_params(self.model))
        self.assertIn("policy_daily_cost", result.history.columns)
        self.assertIn("policy_total_cost", result.summary)
        self.assertIn("estimated_policy_benefit", result.summary)
        self.assertIn("policy_cost_benefit_ratio", result.summary)
        self.assertGreater(result.summary["policy_total_cost"], 0.0)
        self.assertTrue(result.policy_events)
        self.assertTrue(any(event["cost"] > 0 for event in result.policy_events))

    def test_gap03_batch_comparison_shows_cost_benefit_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = run_batch_experiments(
                input_dir=INPUT_DIR,
                scenarios=["default_single_supplier_disruption"],
                output_dir=Path(tmp_dir) / "gap03_batch",
                policy_profiles=["baseline", "no_priority_repair"],
                standardized_output_dir=Path(tmp_dir) / "standardized",
            )
            summary_df = pd.read_csv(payload["summary_csv"])
            baseline = summary_df.loc[summary_df["policy_profile"] == "baseline"].iloc[0]
            without_priority = summary_df.loc[summary_df["policy_profile"] == "no_priority_repair"].iloc[0]
            self.assertGreater(float(baseline["policy_total_cost"]), float(without_priority["policy_total_cost"]))
            self.assertEqual(str(baseline["reference_policy_profile"]), "no_priority_repair")
            self.assertGreater(float(baseline["benefit_vs_reference"]), 0.0)

    def test_policy_profiles_cover_expected_strategy_combinations(self) -> None:
        expected_enabled = {
            "all_policies": {
                "backup_supplier_switch": True,
                "equivalent_material_substitution": True,
                "priority_repair": True,
            },
            "no_policy": {
                "backup_supplier_switch": False,
                "equivalent_material_substitution": False,
                "priority_repair": False,
            },
            "only_backup_switch": {
                "backup_supplier_switch": True,
                "equivalent_material_substitution": False,
                "priority_repair": False,
            },
            "only_substitution": {
                "backup_supplier_switch": False,
                "equivalent_material_substitution": True,
                "priority_repair": False,
            },
            "only_priority_repair": {
                "backup_supplier_switch": False,
                "equivalent_material_substitution": False,
                "priority_repair": True,
            },
        }
        for profile_name, expected in expected_enabled.items():
            policies = build_policy_set(policy_profile=profile_name)
            actual = {policy.policy_type: policy.enabled for policy in policies}
            self.assertEqual(actual, expected)

    def test_gap04_sensitivity_analysis_exports_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = run_sensitivity_analysis(
                input_dir=INPUT_DIR,
                scenario_name="default_single_supplier_disruption",
                output_dir=Path(tmp_dir) / "sensitivity",
                policy_profile="baseline",
                parameter_grid={
                    "backup_switch_time_days": [3, 10],
                    "incident_duration_factor": [0.75, 1.25],
                },
                standardized_output_dir=Path(tmp_dir) / "standardized",
                random_seed=11,
            )
            self.assertTrue(Path(payload["runs_csv"]).exists())
            self.assertTrue(Path(payload["parameter_response_csv"]).exists())
            self.assertTrue(Path(payload["sensitivity_ranking_csv"]).exists())
            self.assertTrue(Path(payload["ranking_figure"]).exists())
            runs_df = pd.read_csv(payload["runs_csv"])
            ranking_df = pd.read_csv(payload["sensitivity_ranking_csv"])
            self.assertIn("parameter_name", runs_df.columns)
            self.assertIn("applied_parameter_value", runs_df.columns)
            self.assertIn("sensitivity_score", ranking_df.columns)
            self.assertEqual(set(ranking_df["parameter_name"]), {"backup_switch_time_days", "incident_duration_factor"})

    def test_gap04_monte_carlo_exports_robustness_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = run_monte_carlo_experiments(
                input_dir=INPUT_DIR,
                scenarios=["default_single_supplier_disruption"],
                output_dir=Path(tmp_dir) / "monte_carlo",
                policy_profiles=["baseline", "no_priority_repair"],
                trials=3,
                standardized_output_dir=Path(tmp_dir) / "standardized",
                random_seed=13,
            )
            self.assertTrue(Path(payload["samples_csv"]).exists())
            self.assertTrue(Path(payload["robustness_csv"]).exists())
            self.assertTrue(Path(payload["robustness_figure"]).exists())
            samples_df = pd.read_csv(payload["samples_csv"])
            robustness_df = pd.read_csv(payload["robustness_csv"])
            self.assertIn("trial_id", samples_df.columns)
            self.assertIn("single_source_ratio", samples_df.columns)
            self.assertIn("average_service_level_mean", robustness_df.columns)
            self.assertIn("service_level_target_hit_rate", robustness_df.columns)
            self.assertEqual(len(samples_df), 6)

    def test_gap05_report_exports_bom_timeline_and_dashboard_outputs(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), load_default_params(self.model))
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = generate_report(result, tmp_dir)
            self.assertIsNotNone(artifacts.bom_figure_path)
            self.assertIsNone(artifacts.timeline_figure_path)
            self.assertIsNotNone(artifacts.monthly_disrupted_nodes_figure_path)
            self.assertIsNotNone(artifacts.propagation_duration_figure_path)
            self.assertIsNotNone(artifacts.network_history_csv)
            self.assertIsNotNone(artifacts.core_trends_figure_path)
            self.assertIsNotNone(artifacts.supplier_network_figure_path)
            self.assertIsNotNone(artifacts.material_network_figure_path)
            self.assertIsNotNone(artifacts.dashboard_data_json)
            self.assertIsNotNone(artifacts.display_spec_markdown)
            self.assertTrue(Path(artifacts.bom_figure_path).exists())
            self.assertTrue(Path(artifacts.monthly_disrupted_nodes_figure_path).exists())
            self.assertTrue(Path(artifacts.propagation_duration_figure_path).exists())
            self.assertTrue(Path(artifacts.network_history_csv).exists())
            self.assertTrue(Path(artifacts.core_trends_figure_path).exists())
            self.assertTrue(Path(artifacts.supplier_network_figure_path).exists())
            self.assertTrue(Path(artifacts.material_network_figure_path).exists())
            self.assertTrue(Path(artifacts.dashboard_data_json).exists())
            self.assertTrue(Path(artifacts.display_spec_markdown).exists())
            payload = json.loads(Path(artifacts.dashboard_data_json).read_text(encoding="utf-8"))
            display_spec_text = Path(artifacts.display_spec_markdown).read_text(encoding="utf-8")
            network_history = pd.read_csv(artifacts.network_history_csv)
            self.assertIn("kpis", payload)
            self.assertIn("runtime", payload)
            self.assertIn("time_series", payload)
            self.assertIn("network_time_series", payload)
            self.assertIn("network_markers", payload)
            self.assertIn("top_impacted_paths", payload)
            self.assertIn("artifact_paths", payload)
            self.assertTrue(payload["time_series"])
            self.assertTrue(payload["network_time_series"])
            self.assertEqual(len(network_history), len(result.history))
            self.assertIn("supplier_disrupted_nodes", network_history.columns)
            self.assertIn("material_affected_nodes", network_history.columns)
            self.assertIn("bom_edge_disrupted", network_history.columns)
            self.assertIn("supply_edge_backup_active", network_history.columns)
            self.assertIn("t0", payload["network_markers"])
            self.assertIn("t_start", payload["network_markers"])
            self.assertIn("t_peak", payload["network_markers"])
            self.assertIn("t_recovery", payload["network_markers"])
            self.assertIn("network_history_csv", payload["artifact_paths"])
            self.assertIn("core_metric_trends_figure", payload["artifact_paths"])
            self.assertIn("supplier_network_trends_figure", payload["artifact_paths"])
            self.assertIn("material_network_trends_figure", payload["artifact_paths"])
            self.assertIn("monthly_disrupted_nodes_figure", payload["artifact_paths"])
            self.assertIn("propagation_duration_figure", payload["artifact_paths"])
            self.assertIn("display_spec_markdown", payload["artifact_paths"])
            self.assertIn("dashboard_runtime_csv", payload["artifact_paths"])
            self.assertIn("dashboard_kpis_csv", payload["artifact_paths"])
            self.assertIn("dashboard_time_series_csv", payload["artifact_paths"])
            self.assertIn("dashboard_network_markers_csv", payload["artifact_paths"])
            self.assertIn("dashboard_artifact_paths_csv", payload["artifact_paths"])
            self.assertIn("dashboard_csv_index_csv", payload["artifact_paths"])
            dashboard_kpis = Path(payload["artifact_paths"]["dashboard_kpis_csv"])
            dashboard_time_series = Path(payload["artifact_paths"]["dashboard_time_series_csv"])
            dashboard_network_markers = Path(payload["artifact_paths"]["dashboard_network_markers_csv"])
            dashboard_artifact_paths = Path(payload["artifact_paths"]["dashboard_artifact_paths_csv"])
            dashboard_csv_index = Path(payload["artifact_paths"]["dashboard_csv_index_csv"])
            self.assertTrue(dashboard_kpis.exists())
            self.assertTrue(dashboard_time_series.exists())
            self.assertTrue(dashboard_network_markers.exists())
            self.assertTrue(dashboard_artifact_paths.exists())
            self.assertTrue(dashboard_csv_index.exists())
            self.assertTrue(Path(payload["artifact_paths"]["display_spec_markdown"]).exists())
            self.assertIn("主传播逻辑", display_spec_text)
            self.assertIn("BOM 不直接用贝叶斯判定终品是否中断", display_spec_text)
            self.assertIn("视觉编码规则", display_spec_text)
            self.assertIn("scenario_id", pd.read_csv(dashboard_kpis).columns)
            self.assertIn("date", pd.read_csv(dashboard_time_series).columns)
            self.assertIn("marker_id", pd.read_csv(dashboard_network_markers).columns)
            self.assertIn("artifact_key", pd.read_csv(dashboard_artifact_paths).columns)
            self.assertIn("dataset_name", pd.read_csv(dashboard_csv_index).columns)
            self.assertIn("dashboard_runtime", pd.read_csv(dashboard_csv_index)["dataset_name"].tolist())
            self.assertIn("propagation_duration_months", payload["summary"])
            self.assertIn("propagation_stop_date", payload["summary"])

    def test_network_history_export_tolerates_missing_edge_type_and_status(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), load_default_params(self.model))
        mutated = copy.deepcopy(result)
        first_snapshot = mutated.network_snapshots[0]
        first_edge_key = next(iter(first_snapshot["edge_state"]))
        first_snapshot["edge_state"][first_edge_key]["edge_type"] = pd.NA
        first_snapshot["edge_state"][first_edge_key]["status"] = pd.NA
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = generate_report(mutated, tmp_dir)
            network_history = pd.read_csv(artifacts.network_history_csv)
            self.assertTrue(Path(artifacts.network_history_csv).exists())
            self.assertTrue(Path(artifacts.supplier_network_figure_path).exists())
            self.assertTrue(Path(artifacts.material_network_figure_path).exists())
            self.assertIn("unknown_edge_count", network_history.columns)
            self.assertGreaterEqual(int(network_history["unknown_edge_count"].max()), 1)

    def test_gap06_batch_exports_paper_tables_and_rankings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = run_batch_experiments(
                input_dir=INPUT_DIR,
                scenarios=["default_single_supplier_disruption", "default_region_disruption"],
                output_dir=Path(tmp_dir) / "paper_batch",
                policy_profiles=["baseline", "no_priority_repair"],
                report_profile="paper",
                standardized_output_dir=Path(tmp_dir) / "standardized",
            )
            scenario_policy_df = pd.read_csv(payload["paper_scenario_policy_csv"])
            policy_effect_df = pd.read_csv(payload["paper_policy_effect_csv"])
            ranking_df = pd.read_csv(payload["paper_policy_ranking_csv"])
            parameter_df = pd.read_csv(payload["paper_parameter_dimension_csv"])
            self.assertTrue(Path(payload["comparison_figure_path"]).exists())
            self.assertTrue(Path(payload["scenario_figure_path"]).exists())
            self.assertTrue(Path(payload["paper_summary_figure_path"]).exists())
            self.assertIn("scenario_id", scenario_policy_df.columns)
            self.assertIn("policy_profile", scenario_policy_df.columns)
            self.assertIn("net_benefit_vs_reference", scenario_policy_df.columns)
            self.assertIn("best_net_benefit_scenario_count", policy_effect_df.columns)
            self.assertIn("paper_composite_score", ranking_df.columns)
            self.assertIn("paper_rank", ranking_df.columns)
            self.assertTrue(set(ranking_df["paper_rank"]).issubset({1, 2}))
            self.assertIn("dimension_name", parameter_df.columns)

    def test_gap01_json_only_input_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_dir = Path(tmp_dir) / "json_input"
            target_dir.mkdir(parents=True, exist_ok=True)
            for source_path in INPUT_DIR.glob("*.json"):
                shutil.copy2(source_path, target_dir / source_path.name)
            raw_bundle = load_raw_bundle(target_dir)
            standard_bundle = standardize(raw_bundle)
            report = validate_standard_bundle(standard_bundle)
            self.assertTrue(report.is_valid)

    def test_gap01_xlsx_only_input_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_dir = Path(tmp_dir) / "xlsx_input"
            target_dir.mkdir(parents=True, exist_ok=True)
            for source_path in INPUT_DIR.glob("*.csv"):
                frame = pd.read_csv(source_path)
                excel_path = target_dir / f"{source_path.stem}.xlsx"
                frame.to_excel(excel_path, index=False)
            raw_bundle = load_raw_bundle(target_dir)
            standard_bundle = standardize(raw_bundle)
            report = validate_standard_bundle(standard_bundle)
            self.assertTrue(report.is_valid)

    def test_gap01_generic_filenames_and_alias_columns_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_dir = Path(tmp_dir) / "aliased_input"
            target_dir.mkdir(parents=True, exist_ok=True)
            for index, source_path in enumerate(sorted(INPUT_DIR.glob("*.csv")), start=1):
                frame = pd.read_csv(source_path)
                frame = frame.rename(columns={column: _to_snake_case(column) for column in frame.columns})
                frame.to_csv(target_dir / f"table_{index:02d}.csv", index=False)
            raw_bundle = load_raw_bundle(target_dir)
            standard_bundle = standardize(raw_bundle)
            report = validate_standard_bundle(standard_bundle)
            self.assertTrue(report.is_valid)


if __name__ == "__main__":
    unittest.main()


def _to_snake_case(value: str) -> str:
    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", str(value))
    normalized = normalized.replace("-", "_")
    normalized = re.sub(r"[^0-9A-Za-z_]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized.lower()
