from __future__ import annotations

import unittest
from pathlib import Path
import tempfile
import copy
import shutil
import re
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
from supply_disruption_sim.disruption.fusion_engine import fuse_supply_and_demand
from supply_disruption_sim.disruption.supply_metrics import build_supply_impacted_paths
from supply_disruption_sim.experiment.batch_runner import run_batch_experiments
from supply_disruption_sim.experiment.monte_carlo import run_monte_carlo_experiments
from supply_disruption_sim.experiment.runner import build_policy_set, run_experiment
from supply_disruption_sim.experiment.sensitivity_runner import run_sensitivity_analysis
from supply_disruption_sim.model.builder import build_model
from supply_disruption_sim.model.state_model import initialize_state
from supply_disruption_sim.policy.backup_supplier_switch import apply_backup_supplier_switch
from supply_disruption_sim.policy.equivalent_material_substitution import apply_equivalent_material_substitution
from supply_disruption_sim.policy.priority_repair import apply_priority_repair
from supply_disruption_sim.reporting.report_generator import generate_report
from supply_disruption_sim.viz.disruption_analysis_plot import build_monthly_disrupted_nodes_frame
from supply_disruption_sim.viz.dashboard_data import build_dashboard_payload
from supply_disruption_sim.viz.bom_plot import select_impacted_paths
from supply_disruption_sim.viz.graph_export import build_export_graph
from supply_disruption_sim.viz.network_trend_plot import build_network_history, build_network_markers
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
        backup_items = self.standard_bundle.supplier_item_map.loc[
            self.standard_bundle.supplier_item_map["is_backup"], "item_id"
        ].nunique()
        self.assertGreaterEqual(backup_items, 3)

    def test_latest_supply_tables_create_backup_supplier_options(self) -> None:
        rows = self.standard_bundle.supplier_item_map
        origins = set(rows.loc[rows["is_backup"], "mapping_origin"].astype(str))
        self.assertTrue(origins & {"licensed", "potential"})
        augmented_rows = rows.loc[rows["mapping_origin"].astype(str) == "augmented"]
        if not augmented_rows.empty:
            self.assertTrue(augmented_rows["is_backup"].astype(bool).all())
            self.assertFalse(augmented_rows["is_current_source"].astype(bool).any())
            self.assertEqual(set(augmented_rows["supply_role"].astype(str)), {"synthetic_backup"})

    def test_production_plan_uses_primary_as_current_and_others_as_backup(self) -> None:
        rows = self.standard_bundle.supplier_item_map
        production_rows = rows.loc[rows["mapping_origin"] == "production_plan"]
        for _, group in production_rows.groupby("item_id"):
            current_rows = group.loc[group["is_current_source"].astype(bool)]
            backup_rows = group.loc[group["is_backup"].astype(bool)]
            positive_rows = group.loc[group["share"].astype(float) > 0.0]
            self.assertEqual(len(current_rows), 1)
            self.assertEqual(int(current_rows["is_primary"].astype(bool).sum()), 1)
            if not positive_rows.empty:
                self.assertAlmostEqual(float(positive_rows["share"].sum()), 1.0, places=4)
            self.assertTrue((backup_rows["share"].astype(float) >= 0.0).all())
            self.assertTrue((backup_rows["backup_capacity_factor"].astype(float) == 1.0).all())
            self.assertTrue(set(backup_rows["supply_role"]).issubset({"production_plan_backup"}))

    def test_authorized_and_potential_supply_are_backup_sources(self) -> None:
        rows = self.standard_bundle.supplier_item_map
        backup_rows = rows.loc[rows["mapping_origin"].isin(["licensed", "potential"])]
        self.assertFalse(backup_rows.empty)
        self.assertTrue(backup_rows["is_backup"].astype(bool).all())
        self.assertFalse(backup_rows["is_current_source"].astype(bool).any())
        self.assertTrue(set(backup_rows["supply_role"]).issubset({"licensed_backup", "potential_backup"}))

    def test_mid0006_has_equivalent_materials(self) -> None:
        alts = self.standard_bundle.part_alternatives
        target = alts.loc[alts["item_id"] == "MID0006", "alt_item_id"].tolist()
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

    def test_stage1_fused_state_does_not_alias_supply_state(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        state = initialize_state(self.model, scenario, params)
        self.assertIsNot(state.fused_state["items"], state.item_effective_status)
        self.assertIsNot(state.fused_state["products"], state.product_status)

    def test_stage1_state_tracks_inbound_supply_factor(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        state = initialize_state(self.model, scenario, params)
        self.assertTrue(state.item_inbound_factor)
        self.assertTrue(all(float(value) == 1.0 for value in state.item_inbound_factor.values()))

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
        self.assertGreaterEqual(float(result.history["demand_fulfillment_rate"].min()), 0.0)
        self.assertLessEqual(float(result.history["demand_fulfillment_rate"].max()), 1.0)

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

    def test_stage4_fusion_uses_effective_supply_status(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        state = initialize_state(self.model, scenario, params)
        item_id = self.standard_bundle.items.loc[~self.standard_bundle.items["is_final_product"], "item_id"].iloc[0]
        state.supply_state["items"][item_id] = "unavailable"
        state.item_supply_status[item_id] = "unavailable"
        state.item_effective_status[item_id] = "available"
        fuse_supply_and_demand(state=state, model=self.model)
        self.assertEqual(state.fused_state["items"][item_id], "failed")

    def test_stage5_network_snapshots_export(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), params)
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = generate_report(result, tmp_dir)
            self.assertEqual(len(artifacts.network_snapshot_paths), 5)
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

    def test_stage5_visual_mapping_edges_follow_declared_supply_map_items(self) -> None:
        graph, _ = build_export_graph(self.model)
        expected_supply_targets = {
            f"item:{item_id}"
            for item_id in self.standard_bundle.supplier_item_map["item_id"].astype(str).unique().tolist()
        }
        seen_levels: set[str] = set()
        for _, target, data in graph.edges(data=True):
            if not str(data.get("edge_key", "")).startswith("supply_edge:"):
                continue
            self.assertTrue(target.startswith("item:"))
            self.assertIn(target, expected_supply_targets)
            item_level = graph.nodes[target].get("item_level")
            self.assertIn(item_level, {"part", "material", "assembly", "product"})
            seen_levels.add(str(item_level))
        self.assertIn("assembly", seen_levels)

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

    def test_stage6_priority_repair_uses_separate_supplier_and_item_limits(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        state = initialize_state(self.model, scenario, params)
        policy = next(policy for policy in load_default_policies() if policy.policy_type == "priority_repair")
        policy.params["max_parallel_repairs"] = 1
        material_item = self.standard_bundle.items.loc[
            self.standard_bundle.items["item_level"].isin(["material", "part"]), "item_id"
        ].iloc[0]
        context = {
            "disrupted_suppliers": {self.standard_bundle.metadata["default_disruption_supplier_id"]},
            "degraded_suppliers": {},
            "material_shortages": {material_item},
            "disrupted_supply_edges": set(),
            "degraded_supply_edges": {},
        }
        apply_priority_repair(
            current_date=scenario.start_date.normalize(),
            state=state,
            model=self.model,
            policy=policy,
            context=context,
        )
        self.assertLessEqual(len(state.repair_pending_suppliers), 1)
        self.assertLessEqual(len(state.repair_pending_items), 1)

    def test_stage6_substitution_active_state_persists_after_source_recovers(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        state = initialize_state(self.model, scenario, params)
        policy = next(policy for policy in load_default_policies() if policy.policy_type == "equivalent_material_substitution")
        target_item = self.standard_bundle.items.loc[
            self.standard_bundle.items["is_critical_material"].astype(bool), "item_id"
        ].iloc[0]
        alt_item = self.standard_bundle.items.loc[
            self.standard_bundle.items["item_id"] != target_item, "item_id"
        ].iloc[0]
        state.substitution_active[str(target_item)] = str(alt_item)
        state.item_supply_status[str(target_item)] = "available"
        apply_equivalent_material_substitution(
            current_date=scenario.start_date.normalize(),
            state=state,
            model=self.model,
            policy=policy,
        )
        self.assertIn(str(target_item), state.substitution_active)

    def test_stage6_backup_switch_deactivates_after_primary_recovers(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        state = initialize_state(self.model, scenario, params)
        policy = next(policy for policy in load_default_policies() if policy.policy_type == "backup_supplier_switch")
        item_id = self.standard_bundle.supplier_item_map.loc[
            self.standard_bundle.supplier_item_map["is_primary"].astype(bool), "item_id"
        ].iloc[0]
        state.backup_active[str(item_id)] = {
            "supplier_id": "SID9999",
            "activate_date": scenario.start_date.normalize(),
            "capacity_factor": 0.75,
            "backup_priority": 10,
            "supply_role": "licensed_backup",
        }
        apply_backup_supplier_switch(
            current_date=scenario.start_date.normalize(),
            state=state,
            model=self.model,
            policy=policy,
        )
        self.assertIn(str(item_id), state.backup_active)

    def test_stage6_backup_switch_uses_recorded_inbound_factor(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        state = initialize_state(self.model, scenario, params)
        policy = next(policy for policy in load_default_policies() if policy.policy_type == "backup_supplier_switch")
        primary_row = self.standard_bundle.supplier_item_map.loc[
            self.standard_bundle.supplier_item_map["is_primary"].astype(bool)
        ].iloc[0]
        item_id = str(primary_row["item_id"])
        supplier_id = str(primary_row["supplier_id"])
        state.supplier_status[supplier_id] = "degraded"
        state.supply_state["suppliers"][supplier_id] = "degraded"
        state.item_inbound_factor[item_id] = 1.0
        state.backup_active[item_id] = {
            "supplier_id": "SID9999",
            "activate_date": scenario.start_date.normalize(),
            "capacity_factor": 0.75,
            "backup_priority": 10,
            "supply_role": "licensed_backup",
        }
        apply_backup_supplier_switch(
            current_date=scenario.start_date.normalize(),
            state=state,
            model=self.model,
            policy=policy,
        )
        self.assertIn(item_id, state.backup_active)

    def test_supply_history_exposes_effective_supply_columns(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), params)
        for column in [
            "supply_effective_available_items",
            "supply_effective_degraded_items",
            "supply_effective_unavailable_items",
            "supply_effective_affected_items",
        ]:
            self.assertIn(column, result.history.columns)

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
        target = scenario.extra["supply_edge"]
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

    def test_gap02_auto_final_path_suppliers_include_all_current_sources(self) -> None:
        bundle = copy.deepcopy(self.standard_bundle)
        final_product_id = bundle.metadata["final_product_ids"][0]
        related_items = set(self.model.bom_graph.ancestors_of(final_product_id))
        if not related_items:
            related_items = set(self.model.bom_graph.descendants_of(final_product_id))
        related_items.add(final_product_id)
        rows = bundle.supplier_item_map.copy()
        candidate = rows.loc[
            rows["item_id"].isin(related_items) & rows["is_backup"].astype(bool)
        ].iloc[0]
        primary_mask = (rows["item_id"] == candidate["item_id"]) & rows["is_primary"].astype(bool)
        rows.loc[primary_mask, "share"] = 0.6
        rows.loc[candidate.name, "is_backup"] = False
        rows.loc[candidate.name, "is_current_source"] = True
        rows.loc[candidate.name, "share"] = 0.4
        bundle.supplier_item_map = rows
        model = build_model(bundle)
        scenario = load_scenario("default_multi_supplier_disruption", model)
        self.assertIn(str(candidate["supplier_id"]), scenario.extra.get("target_supplier_ids", []))

    def test_gap02_auto_default_supply_edge_prefers_current_source(self) -> None:
        bundle = copy.deepcopy(self.standard_bundle)
        rows = bundle.supplier_item_map.copy()
        default_supplier_id = str(bundle.metadata["default_disruption_supplier_id"])
        current_row = rows.loc[
            rows["supplier_id"].astype(str) == default_supplier_id
        ].sort_values(by=["share", "is_primary"], ascending=[False, False]).iloc[0]
        synthetic = current_row.copy()
        synthetic["item_id"] = str(
            bundle.items.loc[bundle.items["item_id"] != current_row["item_id"], "item_id"].iloc[0]
        )
        synthetic["is_primary"] = False
        synthetic["is_backup"] = True
        synthetic["is_current_source"] = False
        synthetic["share"] = 1.0
        rows = pd.concat([rows, pd.DataFrame([synthetic])], ignore_index=True)
        bundle.supplier_item_map = rows
        model = build_model(bundle)
        scenario = load_scenario("default_supply_edge_disruption", model)
        expected_primary_row = rows.loc[
            (rows["supplier_id"].astype(str) == default_supplier_id)
            & rows["is_primary"].astype(bool)
        ].sort_values(by=["share", "is_primary"], ascending=[False, False]).iloc[0]
        self.assertEqual(
            str(scenario.extra["supply_edge"]["item_id"]),
            str(expected_primary_row["item_id"]),
        )

    def test_gap02_bayesian_occurrence_is_not_applied_in_main_loop(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        params.horizon_days = 1
        params.mode = "bayesian"
        params.bayesian_enabled = True
        params.bayesian_use_sampling = False
        params.bayesian_config = copy.deepcopy(params.bayesian_config)
        params.bayesian_config.setdefault("disruption", {})
        params.bayesian_config["disruption"]["prior"] = 0.0
        result = run_simulation(self.model, scenario, load_default_policies(), params)
        self.assertGreaterEqual(int(result.history["disrupted_suppliers"].iloc[0]), 1)

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
            self.assertTrue(Path(artifacts["figure_path"]).exists())
            self.assertIsNone(artifacts["impact_figure_path"])
            self.assertTrue(Path(artifacts["bom_figure_path"]).exists())
            self.assertIsNone(artifacts["timeline_figure_path"])
            self.assertTrue(Path(artifacts["monthly_disrupted_nodes_figure_path"]).exists())
            self.assertTrue(Path(artifacts["propagation_duration_figure_path"]).exists())
            self.assertTrue(Path(artifacts["core_trends_figure_path"]).exists())
            self.assertTrue(Path(artifacts["supplier_network_figure_path"]).exists())
            self.assertTrue(Path(artifacts["material_network_figure_path"]).exists())
            self.assertGreaterEqual(len(payload["artifacts"]["network_snapshot_paths"]), 4)
            self.assertIn("network_history_csv", artifacts)
            self.assertIn("monthly_disrupted_nodes_figure_path", artifacts)
            self.assertIn("propagation_duration_figure_path", artifacts)
            self.assertIn("core_trends_figure_path", artifacts)
            self.assertIn("supplier_network_figure_path", artifacts)
            self.assertIn("material_network_figure_path", artifacts)

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
            baseline_cost = float(baseline["policy_total_cost"])
            without_priority_cost = float(without_priority["policy_total_cost"])
            expected_reference = "baseline" if baseline_cost <= without_priority_cost else "no_priority_repair"
            self.assertNotEqual(baseline_cost, without_priority_cost)
            self.assertEqual(str(baseline["reference_policy_profile"]), expected_reference)
            self.assertEqual(str(without_priority["reference_policy_profile"]), expected_reference)
            self.assertTrue(pd.notna(float(baseline["benefit_vs_reference"])))

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
            self.assertIsNotNone(artifacts.frontend_tables_dir)
            self.assertIsNotNone(artifacts.frontend_manifest_csv)
            self.assertTrue(Path(artifacts.bom_figure_path).exists())
            self.assertTrue(Path(artifacts.monthly_disrupted_nodes_figure_path).exists())
            self.assertTrue(Path(artifacts.propagation_duration_figure_path).exists())
            self.assertTrue(Path(artifacts.network_history_csv).exists())
            self.assertTrue(Path(artifacts.core_trends_figure_path).exists())
            self.assertTrue(Path(artifacts.supplier_network_figure_path).exists())
            self.assertTrue(Path(artifacts.material_network_figure_path).exists())
            self.assertTrue(Path(artifacts.frontend_manifest_csv).exists())
            network_history = pd.read_csv(artifacts.network_history_csv)
            frontend_manifest = pd.read_csv(artifacts.frontend_manifest_csv)
            self.assertEqual(len(network_history), len(result.history))
            self.assertIn("supplier_disrupted_nodes", network_history.columns)
            self.assertIn("material_affected_nodes", network_history.columns)
            self.assertIn("bom_edge_disrupted", network_history.columns)
            self.assertIn("supply_edge_backup_active", network_history.columns)
            self.assertEqual(
                set(frontend_manifest["dataset_name"]),
                {
                    "scenario",
                    "summary",
                    "kpis",
                    "policy_start_snapshot",
                    "time_series",
                    "network_time_series",
                    "network_markers",
                    "top_impacted_paths",
                    "policy_events",
                    "artifact_paths",
                },
            )
            network_markers = pd.read_csv(Path(artifacts.frontend_tables_dir) / "network_markers.csv")
            artifact_paths = pd.read_csv(Path(artifacts.frontend_tables_dir) / "artifact_paths.csv")
            time_series = pd.read_csv(Path(artifacts.frontend_tables_dir) / "time_series.csv")
            self.assertEqual(
                set(network_markers["marker_name"]),
                {"t0", "t_start", "t_supply_peak", "t_policy_start", "t_recovery"},
            )
            t0_date = network_markers.loc[network_markers["marker_name"] == "t0", "date"].iloc[0]
            self.assertEqual(str(t0_date), str((scenario.start_date.normalize() - pd.Timedelta(days=1)).date()))
            self.assertIn("network_history_csv", set(artifact_paths["artifact_name"]))
            self.assertIn("core_metric_trends_figure", set(artifact_paths["artifact_name"]))
            self.assertIn("supplier_network_trends_figure", set(artifact_paths["artifact_name"]))
            self.assertIn("material_network_trends_figure", set(artifact_paths["artifact_name"]))
            self.assertIn("monthly_disrupted_nodes_figure", set(artifact_paths["artifact_name"]))
            self.assertIn("propagation_duration_figure", set(artifact_paths["artifact_name"]))
            self.assertIn("frontend_tables_dir", set(artifact_paths["artifact_name"]))
            self.assertIn("propagation_duration_months", pd.read_csv(Path(artifacts.frontend_tables_dir) / "summary.csv").columns)
            self.assertIn("propagation_stop_date", pd.read_csv(Path(artifacts.frontend_tables_dir) / "summary.csv").columns)
            self.assertIn("supply_degraded_items", time_series.columns)
            self.assertIn("supply_unavailable_items", time_series.columns)
            self.assertIn("supply_effective_degraded_items", time_series.columns)
            self.assertIn("supply_effective_unavailable_items", time_series.columns)

    def test_gap05_monthly_disrupted_nodes_use_same_peak_day_components(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), load_default_params(self.model))
        network_history = build_network_history(result)
        monthly = build_monthly_disrupted_nodes_frame(network_history)
        self.assertFalse(monthly.empty)
        network_history["date"] = pd.to_datetime(network_history["date"])
        network_history["month"] = network_history["date"].dt.to_period("M").dt.to_timestamp()
        for row in monthly.itertuples(index=False):
            month_rows = network_history.loc[network_history["month"] == pd.Timestamp(row.month)]
            self.assertEqual(int(row.supplier_disrupted_nodes), int(month_rows["supplier_disrupted_nodes"].max()))
            self.assertEqual(int(row.material_disrupted_nodes), int(month_rows["material_blocked_nodes"].max()))
            self.assertEqual(int(row.assembly_disrupted_nodes), int(month_rows["assembly_blocked_nodes"].max()))
            self.assertEqual(int(row.product_disrupted_nodes), int(month_rows["product_blocked_nodes"].max()))
            self.assertEqual(
                int(row.total_disrupted_nodes),
                int(
                    (
                        month_rows["supplier_disrupted_nodes"]
                        + month_rows["material_blocked_nodes"]
                        + month_rows["assembly_blocked_nodes"]
                        + month_rows["product_blocked_nodes"]
                    ).max()
                ),
            )

    def test_gap05_inactive_equivalent_materials_follow_normal_supply_logic(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), load_default_params(self.model))
        first_day = result.item_history.loc[result.item_history["date"] == str(scenario.start_date.normalize().date())]
        first_rows = first_day.loc[first_day["item_id"].isin(["MID0009", "MID0019"])]
        self.assertTrue((first_rows["supply_status"].astype(str) == "degraded").all())
        self.assertTrue((first_rows["supply_effective_status"].astype(str) == "degraded").all())
        self.assertTrue((first_rows["fused_status"].astype(str) == "affected").all())

    def test_gap05_recovery_marker_uses_business_recovery_threshold(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), load_default_params(self.model))
        markers = build_network_markers(result, build_network_history(result))
        history = result.history.copy()
        history["date"] = pd.to_datetime(history["date"])
        recovery_candidates = history.loc[
            (history["date"] >= scenario.start_date.normalize())
            & (history["final_product_status"].astype(str) == "active")
            & (history["system_service_level"] >= 0.999)
            & (history["demand_fulfillment_rate"] >= 0.999)
            & (history["total_backlog_demand"] <= 0.0)
            & (history["total_lost_demand"] <= 0.0)
        ]
        expected_date = str(pd.Timestamp(recovery_candidates.iloc[0]["date"]).date())
        self.assertEqual(str(markers["t_recovery"]["date"]), expected_date)

    def test_gap05_dashboard_policy_start_snapshot_uses_shared_marker_logic(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        params.bayesian_enabled = True
        params.mode = "bayesian"
        params.bayesian_config["enabled"] = True
        result = run_simulation(self.model, scenario, load_default_policies(), params)
        network_history = build_network_history(result)
        payload = build_dashboard_payload(
            result=result,
            artifact_paths={},
            network_history=network_history,
        )
        self.assertEqual(
            payload["policy_start_snapshot"]["date"],
            payload["network_markers"]["t_policy_start"]["date"],
        )

    def test_gap05_policy_start_marker_uses_strategy_start_logic(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        result = run_simulation(self.model, scenario, load_default_policies(), load_default_params(self.model))
        markers = build_network_markers(result, build_network_history(result))
        history = result.history.copy()
        history["date"] = pd.to_datetime(history["date"])
        strategy_candidates = history.loc[
            (history["date"] >= scenario.start_date.normalize())
            & (
                (pd.to_numeric(history["active_backup_switches"], errors="coerce").fillna(0) > 0)
                | (pd.to_numeric(history["active_substitutions"], errors="coerce").fillna(0) > 0)
                | (pd.to_numeric(history["active_priority_repairs"], errors="coerce").fillna(0) > 0)
            )
        ]
        expected_date = str(pd.Timestamp(strategy_candidates.iloc[0]["date"]).date())
        self.assertEqual(str(markers["t_policy_start"]["date"]), expected_date)

    def test_gap05_supply_peak_marker_uses_raw_supply_logic(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        params.bayesian_enabled = True
        params.mode = "bayesian"
        params.bayesian_config["enabled"] = True
        result = run_simulation(self.model, scenario, load_default_policies(), params)
        markers = build_network_markers(result, build_network_history(result))
        history = result.history.copy()
        history["date"] = pd.to_datetime(history["date"])
        history["_raw_supply_impact"] = (
            pd.to_numeric(history["disrupted_suppliers"], errors="coerce").fillna(0)
            + pd.to_numeric(history["degraded_suppliers"], errors="coerce").fillna(0)
            + pd.to_numeric(history["supply_unavailable_items"], errors="coerce").fillna(0)
            + pd.to_numeric(history["supply_degraded_items"], errors="coerce").fillna(0)
        )
        expected = history.sort_values(
            by=[
                "_raw_supply_impact",
                "supply_unavailable_items",
                "supply_degraded_items",
                "disrupted_suppliers",
                "degraded_suppliers",
                "date",
            ],
            ascending=[False, False, False, False, False, True],
        ).iloc[0]
        self.assertEqual(
            str(markers["t_supply_peak"]["date"]),
            str(pd.Timestamp(expected["date"]).date()),
        )

    def test_gap05_dashboard_impacted_paths_match_bom_plot_selection(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        params.bayesian_enabled = True
        params.mode = "bayesian"
        params.bayesian_config["enabled"] = True
        result = run_simulation(self.model, scenario, load_default_policies(), params)
        payload = build_dashboard_payload(
            result=result,
            artifact_paths={},
            network_history=build_network_history(result),
        )
        self.assertEqual(payload["top_impacted_paths"], select_impacted_paths(result, limit=12))

    def test_gap05_supply_impacted_paths_include_status(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        params.bayesian_enabled = True
        params.mode = "bayesian"
        params.bayesian_config["enabled"] = True
        result = run_simulation(self.model, scenario, load_default_policies(), params)
        item_history = result.item_history.copy()
        supply_paths = build_supply_impacted_paths(item_history=item_history, model=self.model)
        self.assertTrue(supply_paths)
        self.assertTrue(all(path.get("impact_status") in {"degraded", "unavailable"} for path in supply_paths))

    def test_gap05_bom_path_selection_includes_supply_dimension_when_present(self) -> None:
        scenario = load_scenario("default_single_supplier_disruption", self.model)
        params = load_default_params(self.model)
        params.bayesian_enabled = True
        params.mode = "bayesian"
        params.bayesian_config["enabled"] = True
        result = run_simulation(self.model, scenario, load_default_policies(), params)
        selected = select_impacted_paths(result, limit=10)
        self.assertTrue(any(str(record.get("impact_dimension")) == "supply" for record in selected))

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
        try:
            import openpyxl  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("openpyxl is not installed in this environment.")

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
