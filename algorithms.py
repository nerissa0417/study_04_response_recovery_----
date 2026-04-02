from __future__ import annotations

from collections import Counter

from xd_supply_chain.studies.study_04_response_recovery.monthly_data_builder import (
    HISTORY_MONTHS,
    TOTAL_MONTHS,
    build_monthly_dataset_payload,
)


def _scenario_key(node_scope: str, supplier_mode: str) -> str:
    return f"{node_scope}_{supplier_mode}"


def _forecast_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row["Month_Index"] > HISTORY_MONTHS]


def _count_interrupted_rows(rows: list[dict]) -> int:
    return sum(1 for row in rows if row["Final_Status"] == "interrupted")


def _active_supplier_rows(payload: dict) -> list[dict]:
    if payload["metadata"]["supplier_mode"] == "supply":
        return payload["supplier_monthly_supply_state"]
    return payload["supplier_monthly_demand_state"]


def _build_monthly_status_summary(rows: list[dict], id_field: str) -> list[dict]:
    grouped: dict[int, Counter] = {}
    interrupted_nodes_by_month: dict[int, set[str]] = {}
    for row in rows:
        month_index = row["Month_Index"]
        grouped.setdefault(month_index, Counter())
        grouped[month_index][row["Final_Status"]] += 1
        if row["Final_Status"] == "interrupted":
            interrupted_nodes_by_month.setdefault(month_index, set()).add(row[id_field])

    summary_rows = []
    for month_index in range(1, TOTAL_MONTHS + 1):
        counter = grouped.get(month_index, Counter())
        summary_rows.append(
            {
                "Month_Index": month_index,
                "Interrupted_Count": counter.get("interrupted", 0),
                "Affected_Count": counter.get("affected", 0),
                "Normal_Count": counter.get("normal", 0),
                "Interrupted_Node_IDs": sorted(interrupted_nodes_by_month.get(month_index, set())),
            }
        )
    return summary_rows


class ResponseRecoveryAlgorithm:
    def run(self, input_data: dict, dependency_payloads: dict[str, dict]) -> dict:
        source_tables = input_data["source_tables"]
        critical_material_ids = set(input_data.get("critical_material_ids", []))
        critical_supplier_ids = set(input_data.get("critical_supplier_ids", []))
        scenario_results: dict[str, dict] = {}
        scenario_matrix_rows: list[dict] = []

        for node_scope in input_data["node_scopes"]:
            for supplier_mode in input_data["supplier_modes"]:
                scenario_key = _scenario_key(node_scope, supplier_mode)
                baseline_payload = build_monthly_dataset_payload(
                    source_tables=source_tables,
                    allow_recovery_actions=False,
                    supplier_mode=supplier_mode,
                    node_scope=node_scope,
                    critical_material_ids=critical_material_ids,
                    critical_supplier_ids=critical_supplier_ids,
                    scenario_tuning=input_data.get("scenario_tuning", {}),
                )
                strategy_payload = build_monthly_dataset_payload(
                    source_tables=source_tables,
                    allow_recovery_actions=True,
                    supplier_mode=supplier_mode,
                    node_scope=node_scope,
                    critical_material_ids=critical_material_ids,
                    critical_supplier_ids=critical_supplier_ids,
                    scenario_tuning=input_data.get("scenario_tuning", {}),
                )

                baseline_material_forecast = _forecast_rows(baseline_payload["material_monthly_state"])
                strategy_material_forecast = _forecast_rows(strategy_payload["material_monthly_state"])
                baseline_supplier_forecast = _forecast_rows(_active_supplier_rows(baseline_payload))
                strategy_supplier_forecast = _forecast_rows(_active_supplier_rows(strategy_payload))

                forecast_summary = {
                    "scenario_key": scenario_key,
                    "node_scope": node_scope,
                    "supplier_mode": supplier_mode,
                    "baseline_material_interruption_rows": _count_interrupted_rows(
                        baseline_material_forecast
                    ),
                    "strategy_material_interruption_rows": _count_interrupted_rows(
                        strategy_material_forecast
                    ),
                    "baseline_supplier_interruption_rows": _count_interrupted_rows(
                        baseline_supplier_forecast
                    ),
                    "strategy_supplier_interruption_rows": _count_interrupted_rows(
                        strategy_supplier_forecast
                    ),
                }

                scenario_results[scenario_key] = {
                    "scenario_key": scenario_key,
                    "node_scope": node_scope,
                    "supplier_mode": supplier_mode,
                    "baseline_payload": baseline_payload,
                    "strategy_payload": strategy_payload,
                    "material_monthly_summary": _build_monthly_status_summary(
                        strategy_payload["material_monthly_state"],
                        "Material_ID",
                    ),
                    "supplier_monthly_summary": _build_monthly_status_summary(
                        _active_supplier_rows(strategy_payload),
                        "Supplier_ID",
                    ),
                    "forecast_interruption_summary": forecast_summary,
                }
                scenario_matrix_rows.append(
                    {
                        "Scenario_Key": scenario_key,
                        "Node_Scope": node_scope,
                        "Supplier_Mode": supplier_mode,
                        "Recovery_Strategy": "strategy_a_local_replenishment"
                        if node_scope == "general"
                        else "strategy_b_priority_linked_replenishment",
                        "Baseline_Material_Interrupted_Rows": forecast_summary[
                            "baseline_material_interruption_rows"
                        ],
                        "Strategy_Material_Interrupted_Rows": forecast_summary[
                            "strategy_material_interruption_rows"
                        ],
                        "Baseline_Supplier_Interrupted_Rows": forecast_summary[
                            "baseline_supplier_interruption_rows"
                        ],
                        "Strategy_Supplier_Interrupted_Rows": forecast_summary[
                            "strategy_supplier_interruption_rows"
                        ],
                    }
                )

        default_scenario_key = input_data["default_scenario_key"]
        if default_scenario_key not in scenario_results:
            default_scenario_key = sorted(scenario_results)[0]
        default_result = scenario_results[default_scenario_key]

        return {
            "scenario_results": scenario_results,
            "scenario_strategy_matrix": scenario_matrix_rows,
            "default_scenario_key": default_scenario_key,
            "baseline_payload": default_result["baseline_payload"],
            "strategy_payload": default_result["strategy_payload"],
            "material_monthly_summary": default_result["material_monthly_summary"],
            "supplier_supply_monthly_summary": (
                default_result["supplier_monthly_summary"]
                if default_result["supplier_mode"] == "supply"
                else []
            ),
            "supplier_demand_monthly_summary": (
                default_result["supplier_monthly_summary"]
                if default_result["supplier_mode"] == "demand"
                else []
            ),
            "forecast_interruption_summary": default_result["forecast_interruption_summary"],
        }
