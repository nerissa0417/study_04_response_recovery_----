from __future__ import annotations


def _forecast_new_interruptions(material_rows: list[dict]) -> list[dict]:
    return [
        row
        for row in material_rows
        if row["Month_Index"] > 6
        and row["Final_Status"] == "interrupted"
        and row["Is_New_Interruption"] == 1
    ]


class ResponseRecoveryModel:
    def build(self, input_data: dict, intermediate_data: dict, dependency_payloads: dict[str, dict]) -> dict:
        response_target_hours = input_data["response_target_hours"]
        scenario_models: dict[str, dict] = {}

        for scenario_key, scenario_result in intermediate_data["scenario_results"].items():
            strategy_payload = scenario_result["strategy_payload"]
            baseline_payload = scenario_result["baseline_payload"]
            response_playbooks = []
            for row in _forecast_new_interruptions(strategy_payload["material_monthly_state"]):
                response_level = "level_1" if row["Is_Critical_Material"] == 1 else "level_2"
                response_playbooks.append(
                    {
                        "scenario_id": f"{scenario_key}_{row['Material_ID']}_m{row['Month_Index']}",
                        "month_index": row["Month_Index"],
                        "material_id": row["Material_ID"],
                        "material_name": row["Material_Name"],
                        "response_level": response_level,
                        "trigger_reason": row["Interruption_Trigger_Reason"],
                        "supplier_mode": scenario_result["supplier_mode"],
                        "node_scope": scenario_result["node_scope"],
                        "steps": [
                            {"step": 1, "action": "confirm_interruption", "target_hours": 2},
                            {"step": 2, "action": "check_material_balance", "target_hours": 4},
                            {"step": 3, "action": "schedule_replenishment", "target_hours": 8},
                            {
                                "step": 4,
                                "action": "stabilize_next_month_supply",
                                "target_hours": response_target_hours,
                            },
                        ],
                    }
                )

            recovery_plans = [
                {
                    "plan_id": f"{scenario_key}_plan_{index:03d}",
                    "scenario_key": scenario_key,
                    "decision_month": row["Decision_Month"],
                    "effective_month": row["Effective_Month"],
                    "strategy_type": row["Strategy_Type"],
                    "interruption_scope": row["Interruption_Scope"],
                    "supplier_mode": row["Supplier_Mode"],
                    "source_material_id": row["Source_Material_ID"],
                    "target_material_id": row["Target_Material_ID"],
                    "planned_replenishment_qty": row["Planned_Replenishment_Qty"],
                    "linked_supplier_ids": row.get("Linked_Supplier_IDs", ""),
                    "timing_rule": row["Timing_Rule"],
                }
                for index, row in enumerate(strategy_payload["recovery_actions"], start=1)
            ]

            scenario_models[scenario_key] = {
                "scenario_key": scenario_key,
                "node_scope": scenario_result["node_scope"],
                "supplier_mode": scenario_result["supplier_mode"],
                "monthly_interruption_data": strategy_payload,
                "baseline_monthly_interruption_data": baseline_payload,
                "material_monthly_summary": scenario_result["material_monthly_summary"],
                "supplier_monthly_summary": scenario_result["supplier_monthly_summary"],
                "forecast_interruption_summary": scenario_result["forecast_interruption_summary"],
                "response_playbooks": response_playbooks,
                "recovery_plans": recovery_plans,
            }

        default_scenario_key = intermediate_data["default_scenario_key"]
        default_model = scenario_models[default_scenario_key]

        return {
            "scenario_models": scenario_models,
            "scenario_strategy_matrix": intermediate_data["scenario_strategy_matrix"],
            "default_scenario_key": default_scenario_key,
            "monthly_interruption_data": default_model["monthly_interruption_data"],
            "baseline_monthly_interruption_data": default_model["baseline_monthly_interruption_data"],
            "material_monthly_summary": default_model["material_monthly_summary"],
            "supplier_supply_monthly_summary": (
                default_model["supplier_monthly_summary"]
                if default_model["supplier_mode"] == "supply"
                else []
            ),
            "supplier_demand_monthly_summary": (
                default_model["supplier_monthly_summary"]
                if default_model["supplier_mode"] == "demand"
                else []
            ),
            "forecast_interruption_summary": default_model["forecast_interruption_summary"],
            "response_playbooks": default_model["response_playbooks"],
            "recovery_plans": default_model["recovery_plans"],
        }
