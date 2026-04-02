from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from xd_supply_chain.studies.study_04_response_recovery.visualization import (
    build_dashboard_visualization_html,
    build_dashboard_visualization_payload,
    build_network_visualization_html,
    build_network_visualization_payload,
)


def _dump_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _dump_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _active_supplier_rows(payload: dict) -> list[dict]:
    if payload["metadata"]["supplier_mode"] == "supply":
        return payload["supplier_monthly_supply_state"]
    return payload["supplier_monthly_demand_state"]


def _monthly_interrupted_counts(rows: list[dict], key_field: str) -> dict[int, int]:
    counts: dict[int, set[str]] = {}
    for row in rows:
        if row["Final_Status"] != "interrupted":
            continue
        counts.setdefault(row["Month_Index"], set()).add(row[key_field])
    return {month_index: len(node_ids) for month_index, node_ids in counts.items()}


def _monthly_metric_sum(rows: list[dict], metric_field: str) -> dict[int, float]:
    totals: dict[int, float] = {}
    for row in rows:
        month_index = row["Month_Index"]
        totals[month_index] = totals.get(month_index, 0.0) + float(row.get(metric_field, 0) or 0)
    return totals


def _monthly_scope_counts(
    material_rows: list[dict],
    supplier_rows: list[dict],
) -> dict[int, dict[str, int]]:
    scope_lookup: dict[int, dict[str, set[str]]] = defaultdict(
        lambda: {"material": set(), "supplier": set()}
    )
    for row in material_rows:
        if row["Final_Status"] in {"affected", "interrupted"}:
            scope_lookup[row["Month_Index"]]["material"].add(row["Material_ID"])
    for row in supplier_rows:
        if row["Final_Status"] in {"affected", "interrupted"}:
            scope_lookup[row["Month_Index"]]["supplier"].add(row["Supplier_ID"])
    return {
        month_index: {
            "Material_Scope_Node_Count": len(bucket["material"]),
            "Supplier_Scope_Node_Count": len(bucket["supplier"]),
            "Scope_Node_Count": len(bucket["material"]) + len(bucket["supplier"]),
        }
        for month_index, bucket in scope_lookup.items()
    }


def _continuous_interruption_stats(
    rows: list[dict],
    key_field: str,
    label_field: str,
    node_type: str,
) -> dict[str, dict]:
    forecast_rows = sorted(
        (row for row in rows if row["Month_Index"] > 6),
        key=lambda row: (row[key_field], row["Month_Index"]),
    )
    current_runs: dict[str, int] = defaultdict(int)
    max_runs: dict[str, int] = defaultdict(int)
    interrupted_months: dict[str, int] = defaultdict(int)
    labels: dict[str, str] = {}

    for row in forecast_rows:
        node_id = row[key_field]
        labels[node_id] = row.get(label_field, node_id)
        if row["Final_Status"] == "interrupted":
            current_runs[node_id] += 1
            interrupted_months[node_id] += 1
            max_runs[node_id] = max(max_runs[node_id], current_runs[node_id])
        else:
            current_runs[node_id] = 0

    return {
        node_id: {
            "Node_ID": node_id,
            "Node_Name": labels.get(node_id, node_id),
            "Node_Type": node_type,
            "Max_Continuous_Interrupted_Months": max_runs.get(node_id, 0),
            "Interrupted_Months": interrupted_months.get(node_id, 0),
        }
        for node_id in labels
    }


def _build_continuous_comparison_rows(
    baseline_material_rows: list[dict],
    strategy_material_rows: list[dict],
    baseline_supplier_rows: list[dict],
    strategy_supplier_rows: list[dict],
    scenario_key: str,
    node_scope: str,
    supplier_mode: str,
) -> list[dict]:
    baseline_stats = {}
    baseline_stats.update(
        _continuous_interruption_stats(
            baseline_material_rows,
            "Material_ID",
            "Material_Name",
            "material",
        )
    )
    baseline_stats.update(
        _continuous_interruption_stats(
            baseline_supplier_rows,
            "Supplier_ID",
            "Supplier_Name",
            "supplier",
        )
    )
    strategy_stats = {}
    strategy_stats.update(
        _continuous_interruption_stats(
            strategy_material_rows,
            "Material_ID",
            "Material_Name",
            "material",
        )
    )
    strategy_stats.update(
        _continuous_interruption_stats(
            strategy_supplier_rows,
            "Supplier_ID",
            "Supplier_Name",
            "supplier",
        )
    )

    rows = []
    for node_id in sorted(set(baseline_stats) | set(strategy_stats)):
        baseline_row = baseline_stats.get(node_id, {})
        strategy_row = strategy_stats.get(node_id, {})
        rows.append(
            {
                "Scenario_Key": scenario_key,
                "Node_Scope": node_scope,
                "Supplier_Mode": supplier_mode,
                "Node_ID": node_id,
                "Node_Label": strategy_row.get("Node_Name", baseline_row.get("Node_Name", node_id)),
                "Node_Name": strategy_row.get("Node_Name", baseline_row.get("Node_Name", node_id)),
                "Node_Type": strategy_row.get("Node_Type", baseline_row.get("Node_Type", "")),
                "Baseline_Max_Continuous_Interrupted_Months": baseline_row.get(
                    "Max_Continuous_Interrupted_Months",
                    0,
                ),
                "Strategy_Max_Continuous_Interrupted_Months": strategy_row.get(
                    "Max_Continuous_Interrupted_Months",
                    0,
                ),
                "Recovered_Continuous_Interrupted_Months": baseline_row.get(
                    "Max_Continuous_Interrupted_Months",
                    0,
                )
                - strategy_row.get("Max_Continuous_Interrupted_Months", 0),
                "Baseline_Interrupted_Months": baseline_row.get("Interrupted_Months", 0),
                "Strategy_Interrupted_Months": strategy_row.get("Interrupted_Months", 0),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            -row["Baseline_Max_Continuous_Interrupted_Months"],
            -row["Strategy_Max_Continuous_Interrupted_Months"],
            row["Node_Type"],
            row["Node_ID"],
        ),
    )


class ResponseRecoverySimulator:
    def simulate(
        self,
        input_data: dict,
        intermediate_data: dict,
        output_data: dict,
        dependency_payloads: dict[str, dict],
    ) -> dict:
        response_target_hours = input_data["response_target_hours"]
        study_root = Path(input_data["study_root"])
        export_root = study_root
        sample_root = study_root / "sample_data_12m"
        default_scenario_key = intermediate_data["default_scenario_key"]
        scenario_manifests: dict[str, dict] = {}
        scenario_summaries: dict[str, dict] = {}
        scenario_monthly_comparison_rows: dict[str, list[dict]] = {}
        scenario_continuous_rows: dict[str, list[dict]] = {}
        scenario_recovery_rows: dict[str, list[dict]] = {}
        matrix_rows: list[dict] = []

        for scenario_key, scenario_result in intermediate_data["scenario_results"].items():
            baseline_payload = scenario_result["baseline_payload"]
            strategy_payload = scenario_result["strategy_payload"]
            supplier_mode = scenario_result["supplier_mode"]
            node_scope = scenario_result["node_scope"]
            baseline_supplier_rows = _active_supplier_rows(baseline_payload)
            strategy_supplier_rows = _active_supplier_rows(strategy_payload)

            baseline_material_counts = _monthly_interrupted_counts(
                baseline_payload["material_monthly_state"],
                "Material_ID",
            )
            strategy_material_counts = _monthly_interrupted_counts(
                strategy_payload["material_monthly_state"],
                "Material_ID",
            )
            baseline_supplier_counts = _monthly_interrupted_counts(
                baseline_supplier_rows,
                "Supplier_ID",
            )
            strategy_supplier_counts = _monthly_interrupted_counts(
                strategy_supplier_rows,
                "Supplier_ID",
            )
            baseline_unmet_demand = _monthly_metric_sum(
                baseline_payload["material_monthly_state"],
                "Unmet_Demand_Qty",
            )
            strategy_unmet_demand = _monthly_metric_sum(
                strategy_payload["material_monthly_state"],
                "Unmet_Demand_Qty",
            )
            baseline_end_inventory = _monthly_metric_sum(
                baseline_payload["material_monthly_state"],
                "Inventory_End_Qty",
            )
            strategy_end_inventory = _monthly_metric_sum(
                strategy_payload["material_monthly_state"],
                "Inventory_End_Qty",
            )
            baseline_scope_counts = _monthly_scope_counts(
                baseline_payload["material_monthly_state"],
                baseline_supplier_rows,
            )
            strategy_scope_counts = _monthly_scope_counts(
                strategy_payload["material_monthly_state"],
                strategy_supplier_rows,
            )
            continuous_comparison_rows = _build_continuous_comparison_rows(
                baseline_payload["material_monthly_state"],
                strategy_payload["material_monthly_state"],
                baseline_supplier_rows,
                strategy_supplier_rows,
                scenario_key,
                node_scope,
                supplier_mode,
            )

            monthly_recovery_comparison = []
            for month_index in range(7, 13):
                baseline_unmet_demand_qty = baseline_unmet_demand.get(month_index, 0.0)
                strategy_unmet_demand_qty = strategy_unmet_demand.get(month_index, 0.0)
                baseline_end_inventory_qty = baseline_end_inventory.get(month_index, 0.0)
                strategy_end_inventory_qty = strategy_end_inventory.get(month_index, 0.0)
                baseline_scope = baseline_scope_counts.get(month_index, {})
                strategy_scope = strategy_scope_counts.get(month_index, {})
                monthly_recovery_comparison.append(
                    {
                        "Scenario_Key": scenario_key,
                        "Node_Scope": node_scope,
                        "Supplier_Mode": supplier_mode,
                        "Month_Index": month_index,
                        "Month_Label": strategy_payload["metadata"]["month_labels"][month_index - 1],
                        "Baseline_Material_Interrupted_Count": baseline_material_counts.get(
                            month_index,
                            0,
                        ),
                        "Strategy_Material_Interrupted_Count": strategy_material_counts.get(
                            month_index,
                            0,
                        ),
                        "Baseline_Supplier_Interrupted_Count": baseline_supplier_counts.get(
                            month_index,
                            0,
                        ),
                        "Strategy_Supplier_Interrupted_Count": strategy_supplier_counts.get(
                            month_index,
                            0,
                        ),
                        "Baseline_Scope_Node_Count": baseline_scope.get("Scope_Node_Count", 0),
                        "Strategy_Scope_Node_Count": strategy_scope.get("Scope_Node_Count", 0),
                        "Recovered_Scope_Node_Count": baseline_scope.get("Scope_Node_Count", 0)
                        - strategy_scope.get("Scope_Node_Count", 0),
                        "Baseline_Unmet_Demand_Qty": baseline_unmet_demand_qty,
                        "Strategy_Unmet_Demand_Qty": strategy_unmet_demand_qty,
                        "Recovered_Unmet_Demand_Qty": baseline_unmet_demand_qty
                        - strategy_unmet_demand_qty,
                        "Baseline_End_Inventory_Qty": baseline_end_inventory_qty,
                        "Strategy_End_Inventory_Qty": strategy_end_inventory_qty,
                        "Recovered_End_Inventory_Qty": strategy_end_inventory_qty
                        - baseline_end_inventory_qty,
                    }
                )

            recovery_comparison_rows = []
            for row in monthly_recovery_comparison:
                baseline_load = (
                    row["Baseline_Material_Interrupted_Count"]
                    + row["Baseline_Supplier_Interrupted_Count"]
                )
                strategy_load = (
                    row["Strategy_Material_Interrupted_Count"]
                    + row["Strategy_Supplier_Interrupted_Count"]
                )
                sequential_recovery_hours = baseline_load * response_target_hours
                priority_recovery_hours = strategy_load * response_target_hours
                recovery_comparison_rows.append(
                    {
                        "scenario_id": f"{scenario_key}_forecast_m{row['Month_Index']:02d}",
                        "scenario_key": scenario_key,
                        "month_index": row["Month_Index"],
                        "sequential_recovery_hours": sequential_recovery_hours,
                        "priority_recovery_hours": priority_recovery_hours,
                        "time_saved_hours": sequential_recovery_hours - priority_recovery_hours,
                        "baseline_scope_node_count": row["Baseline_Scope_Node_Count"],
                        "strategy_scope_node_count": row["Strategy_Scope_Node_Count"],
                        "recovered_scope_node_count": row["Recovered_Scope_Node_Count"],
                        "baseline_unmet_demand_qty": row["Baseline_Unmet_Demand_Qty"],
                        "strategy_unmet_demand_qty": row["Strategy_Unmet_Demand_Qty"],
                        "recovered_unmet_demand_qty": row["Recovered_Unmet_Demand_Qty"],
                        "baseline_end_inventory_qty": row["Baseline_End_Inventory_Qty"],
                        "strategy_end_inventory_qty": row["Strategy_End_Inventory_Qty"],
                        "recovered_end_inventory_qty": row["Recovered_End_Inventory_Qty"],
                    }
                )

            scenario_root = export_root / scenario_key
            baseline_root = scenario_root / "baseline"
            strategy_root = scenario_root / "strategy"
            baseline_tables = {
                "material_monthly_state": baseline_payload["material_monthly_state"],
                "supplier_monthly_supply_state": baseline_payload["supplier_monthly_supply_state"],
                "supplier_demand_edge_monthly_state": baseline_payload[
                    "supplier_demand_edge_monthly_state"
                ],
                "supplier_monthly_demand_state": baseline_payload["supplier_monthly_demand_state"],
                "scenario_seed_summary": baseline_payload["scenario_seed_summary"],
            }
            strategy_tables = {
                "material_monthly_state": strategy_payload["material_monthly_state"],
                "supplier_monthly_supply_state": strategy_payload["supplier_monthly_supply_state"],
                "supplier_demand_edge_monthly_state": strategy_payload[
                    "supplier_demand_edge_monthly_state"
                ],
                "supplier_monthly_demand_state": strategy_payload["supplier_monthly_demand_state"],
                "recovery_actions": strategy_payload["recovery_actions"],
                "scenario_seed_summary": strategy_payload["scenario_seed_summary"],
            }
            for table_name, rows in baseline_tables.items():
                _dump_json(baseline_root / f"{table_name}.json", rows)
                _dump_csv(baseline_root / f"{table_name}.csv", rows)
            for table_name, rows in strategy_tables.items():
                _dump_json(strategy_root / f"{table_name}.json", rows)
                _dump_csv(strategy_root / f"{table_name}.csv", rows)

            _dump_json(
                scenario_root / "monthly_recovery_comparison.json",
                monthly_recovery_comparison,
            )
            _dump_csv(
                scenario_root / "monthly_recovery_comparison.csv",
                monthly_recovery_comparison,
            )
            _dump_json(
                scenario_root / "continuous_interruption_comparison.json",
                continuous_comparison_rows,
            )
            _dump_csv(
                scenario_root / "continuous_interruption_comparison.csv",
                continuous_comparison_rows,
            )

            visualization_payload = build_network_visualization_payload(
                source_tables=input_data["source_tables"],
                baseline_payload=baseline_payload,
                strategy_payload=strategy_payload,
                monthly_recovery_comparison=monthly_recovery_comparison,
            )
            network_visualization_json_path = scenario_root / "network_visualization.json"
            network_visualization_html_path = scenario_root / "network_visualization.html"
            _dump_json(network_visualization_json_path, visualization_payload)
            network_visualization_html_path.write_text(
                build_network_visualization_html(visualization_payload),
                encoding="utf-8",
            )
            if scenario_key == default_scenario_key:
                sample_baseline_root = sample_root / "baseline"
                sample_strategy_root = sample_root / "strategy"
                for table_name, rows in baseline_tables.items():
                    _dump_json(sample_baseline_root / f"{table_name}.json", rows)
                    _dump_csv(sample_baseline_root / f"{table_name}.csv", rows)
                for table_name, rows in strategy_tables.items():
                    _dump_json(sample_strategy_root / f"{table_name}.json", rows)
                    _dump_csv(sample_strategy_root / f"{table_name}.csv", rows)
                _dump_json(
                    sample_root / "monthly_recovery_comparison.json",
                    monthly_recovery_comparison,
                )
                _dump_csv(
                    sample_root / "monthly_recovery_comparison.csv",
                    monthly_recovery_comparison,
                )
                _dump_json(
                    sample_root / "continuous_interruption_comparison.json",
                    continuous_comparison_rows,
                )
                _dump_csv(
                    sample_root / "continuous_interruption_comparison.csv",
                    continuous_comparison_rows,
                )
                _dump_json(sample_root / "network_visualization.json", visualization_payload)
                (sample_root / "network_visualization.html").write_text(
                    build_network_visualization_html(visualization_payload),
                    encoding="utf-8",
                )
                _dump_json(
                    sample_root / "sample_data_manifest.json",
                    {
                        "default_scenario_key": default_scenario_key,
                        "sample_root": str(sample_root),
                        "baseline_root": str(sample_baseline_root),
                        "strategy_root": str(sample_strategy_root),
                        "network_visualization_html_path": str(
                            sample_root / "network_visualization.html"
                        ),
                    },
                )

            forecast_unmet_demand_qty_baseline = sum(
                row["Baseline_Unmet_Demand_Qty"] for row in monthly_recovery_comparison
            )
            forecast_unmet_demand_qty_strategy = sum(
                row["Strategy_Unmet_Demand_Qty"] for row in monthly_recovery_comparison
            )
            forecast_end_inventory_qty_baseline = sum(
                row["Baseline_End_Inventory_Qty"] for row in monthly_recovery_comparison
            )
            forecast_end_inventory_qty_strategy = sum(
                row["Strategy_End_Inventory_Qty"] for row in monthly_recovery_comparison
            )
            forecast_scope_node_count_baseline = sum(
                row["Baseline_Scope_Node_Count"] for row in monthly_recovery_comparison
            )
            forecast_scope_node_count_strategy = sum(
                row["Strategy_Scope_Node_Count"] for row in monthly_recovery_comparison
            )
            max_baseline_continuous = max(
                (
                    row["Baseline_Max_Continuous_Interrupted_Months"]
                    for row in continuous_comparison_rows
                ),
                default=0,
            )
            max_strategy_continuous = max(
                (
                    row["Strategy_Max_Continuous_Interrupted_Months"]
                    for row in continuous_comparison_rows
                ),
                default=0,
            )
            scenario_summary = {
                "scenario_key": scenario_key,
                "node_scope": node_scope,
                "supplier_mode": supplier_mode,
                "forecast_material_interruption_rows_baseline": scenario_result[
                    "forecast_interruption_summary"
                ]["baseline_material_interruption_rows"],
                "forecast_material_interruption_rows_strategy": scenario_result[
                    "forecast_interruption_summary"
                ]["strategy_material_interruption_rows"],
                "forecast_supplier_interruption_rows_baseline": scenario_result[
                    "forecast_interruption_summary"
                ]["baseline_supplier_interruption_rows"],
                "forecast_supplier_interruption_rows_strategy": scenario_result[
                    "forecast_interruption_summary"
                ]["strategy_supplier_interruption_rows"],
                "forecast_scope_node_count_baseline": forecast_scope_node_count_baseline,
                "forecast_scope_node_count_strategy": forecast_scope_node_count_strategy,
                "forecast_recovered_scope_node_count": forecast_scope_node_count_baseline
                - forecast_scope_node_count_strategy,
                "forecast_unmet_demand_qty_baseline": forecast_unmet_demand_qty_baseline,
                "forecast_unmet_demand_qty_strategy": forecast_unmet_demand_qty_strategy,
                "forecast_recovered_unmet_demand_qty": forecast_unmet_demand_qty_baseline
                - forecast_unmet_demand_qty_strategy,
                "forecast_end_inventory_qty_baseline": forecast_end_inventory_qty_baseline,
                "forecast_end_inventory_qty_strategy": forecast_end_inventory_qty_strategy,
                "forecast_recovered_end_inventory_qty": forecast_end_inventory_qty_strategy
                - forecast_end_inventory_qty_baseline,
                "max_continuous_interrupted_months_baseline": max_baseline_continuous,
                "max_continuous_interrupted_months_strategy": max_strategy_continuous,
            }
            scenario_manifests[scenario_key] = {
                "scenario_root": str(scenario_root),
                "baseline_root": str(baseline_root),
                "strategy_root": str(strategy_root),
                "comparison_json_path": str(scenario_root / "monthly_recovery_comparison.json"),
                "comparison_csv_path": str(scenario_root / "monthly_recovery_comparison.csv"),
                "continuous_comparison_json_path": str(
                    scenario_root / "continuous_interruption_comparison.json"
                ),
                "continuous_comparison_csv_path": str(
                    scenario_root / "continuous_interruption_comparison.csv"
                ),
                "network_visualization_json_path": str(network_visualization_json_path),
                "network_visualization_html_path": str(network_visualization_html_path),
            }
            scenario_summaries[scenario_key] = scenario_summary
            scenario_monthly_comparison_rows[scenario_key] = monthly_recovery_comparison
            scenario_continuous_rows[scenario_key] = continuous_comparison_rows
            scenario_recovery_rows[scenario_key] = recovery_comparison_rows
            matrix_rows.append(
                {
                    **next(
                        row
                        for row in intermediate_data["scenario_strategy_matrix"]
                        if row["Scenario_Key"] == scenario_key
                    ),
                    "Forecast_Scope_Node_Count_Baseline": forecast_scope_node_count_baseline,
                    "Forecast_Scope_Node_Count_Strategy": forecast_scope_node_count_strategy,
                    "Forecast_Unmet_Demand_Qty_Baseline": forecast_unmet_demand_qty_baseline,
                    "Forecast_Unmet_Demand_Qty_Strategy": forecast_unmet_demand_qty_strategy,
                    "Forecast_End_Inventory_Qty_Baseline": forecast_end_inventory_qty_baseline,
                    "Forecast_End_Inventory_Qty_Strategy": forecast_end_inventory_qty_strategy,
                    "Max_Continuous_Interrupted_Months_Baseline": max_baseline_continuous,
                    "Max_Continuous_Interrupted_Months_Strategy": max_strategy_continuous,
                }
            )

        dashboard_payload = build_dashboard_visualization_payload(
            scenario_summaries=scenario_summaries,
            scenario_monthly_comparison_rows=scenario_monthly_comparison_rows,
            scenario_continuous_rows=scenario_continuous_rows,
            scenario_strategy_matrix=matrix_rows,
            default_scenario_key=default_scenario_key,
        )
        dashboard_json_path = export_root / "scenario_dashboard.json"
        dashboard_html_path = export_root / "scenario_dashboard.html"
        matrix_json_path = export_root / "scenario_strategy_matrix.json"
        matrix_csv_path = export_root / "scenario_strategy_matrix.csv"
        _dump_json(dashboard_json_path, dashboard_payload)
        dashboard_html_path.write_text(
            build_dashboard_visualization_html(dashboard_payload),
            encoding="utf-8",
        )
        _dump_json(matrix_json_path, matrix_rows)
        _dump_csv(matrix_csv_path, matrix_rows)

        return {
            "scenario_recovery_comparison": scenario_recovery_rows,
            "recovery_comparison": scenario_recovery_rows[default_scenario_key],
            "recovery_comparison_summary": scenario_summaries[default_scenario_key],
            "scenario_recovery_summaries": scenario_summaries,
            "export_manifest": {
                "study_root": str(export_root),
                "sample_root": str(sample_root),
                "scenario_manifests": scenario_manifests,
                "dashboard_json_path": str(dashboard_json_path),
                "dashboard_html_path": str(dashboard_html_path),
                "matrix_json_path": str(matrix_json_path),
                "matrix_csv_path": str(matrix_csv_path),
            },
        }
