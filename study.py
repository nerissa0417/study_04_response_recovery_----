from __future__ import annotations

from xd_supply_chain.core.contracts import StudyMetadata
from xd_supply_chain.studies.base import BaseStudy
from xd_supply_chain.studies.study_04_response_recovery.algorithms import (
    ResponseRecoveryAlgorithm,
)
from xd_supply_chain.studies.study_04_response_recovery.io import ResponseRecoveryInputAdapter
from xd_supply_chain.studies.study_04_response_recovery.models import ResponseRecoveryModel
from xd_supply_chain.studies.study_04_response_recovery.simulation import (
    ResponseRecoverySimulator,
)


class Study04ResponseRecovery(BaseStudy):
    metadata = StudyMetadata(
        key="study_04_response_recovery",
        name="Response and recovery strategy",
        stage=4,
        dependencies=("study_00_data", "study_02_network", "study_03_cascade"),
    )

    def __init__(self) -> None:
        super().__init__(
            input_adapter=ResponseRecoveryInputAdapter(),
            algorithm=ResponseRecoveryAlgorithm(),
            model=ResponseRecoveryModel(),
            simulator=ResponseRecoverySimulator(),
        )

    def select_published_data(
        self,
        input_data: dict,
        intermediate_data: dict,
        output_data: dict,
        simulation_data: dict,
    ) -> dict:
        default_scenario_key = output_data["default_scenario_key"]
        default_manifest = simulation_data.get("export_manifest", {}).get("scenario_manifests", {}).get(
            default_scenario_key,
            {},
        )
        return {
            "monthly_output_paths": simulation_data.get("export_manifest", {}),
            "network_visualization_path": default_manifest.get("network_visualization_html_path", ""),
            "scenario_dashboard_path": simulation_data.get("export_manifest", {}).get(
                "dashboard_html_path",
                "",
            ),
            "recovery_comparison_summary": simulation_data.get("recovery_comparison_summary", {}),
            "scenario_recovery_summaries": simulation_data.get("scenario_recovery_summaries", {}),
            "forecast_interruption_summary": output_data["forecast_interruption_summary"],
            "scenario_strategy_matrix": output_data["scenario_strategy_matrix"],
            "default_scenario_key": default_scenario_key,
            "material_monthly_summary": output_data["material_monthly_summary"],
            "supplier_supply_monthly_summary": output_data["supplier_supply_monthly_summary"],
            "supplier_demand_monthly_summary": output_data["supplier_demand_monthly_summary"],
            "response_playbooks": output_data["response_playbooks"],
            "recovery_plans": output_data["recovery_plans"],
            "recovery_comparison": simulation_data["recovery_comparison"],
        }

    def build_summary(
        self,
        input_data: dict,
        intermediate_data: dict,
        output_data: dict,
        simulation_data: dict,
    ) -> str:
        scenario_key = output_data["default_scenario_key"]
        summary = simulation_data.get("scenario_recovery_summaries", {}).get(scenario_key, {})
        return (
            f"Study 04 completed for default scenario `{scenario_key}` with forecast material "
            f"interruptions {summary.get('forecast_material_interruption_rows_baseline', 0)} -> "
            f"{summary.get('forecast_material_interruption_rows_strategy', 0)} and supplier "
            f"interruptions {summary.get('forecast_supplier_interruption_rows_baseline', 0)} -> "
            f"{summary.get('forecast_supplier_interruption_rows_strategy', 0)}. "
            "Scenario dashboard and per-scenario network visualizations exported."
        )
