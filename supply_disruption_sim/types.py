from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(slots=True)
class RawBundle:
    tables: dict[str, pd.DataFrame]
    source_dir: Path


@dataclass(slots=True)
class StandardBundle:
    suppliers: pd.DataFrame
    supplier_edges: pd.DataFrame
    items: pd.DataFrame
    bom_edges: pd.DataFrame
    supplier_item_map: pd.DataFrame
    part_alternatives: pd.DataFrame
    incident_events: pd.DataFrame
    supplier_materials: pd.DataFrame = field(default_factory=pd.DataFrame)
    supplier_production_plan: pd.DataFrame = field(default_factory=pd.DataFrame)
    supplier_licensed_supply: pd.DataFrame = field(default_factory=pd.DataFrame)
    supplier_potential_supply: pd.DataFrame = field(default_factory=pd.DataFrame)
    supplier_daily_inventory: pd.DataFrame = field(default_factory=pd.DataFrame)
    supplier_material_flow_events: pd.DataFrame = field(default_factory=pd.DataFrame)
    supplier_material_inventory_policy: pd.DataFrame = field(default_factory=pd.DataFrame)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, pd.DataFrame]:
        tables = {
            "suppliers": self.suppliers,
            "supplier_edges": self.supplier_edges,
            "items": self.items,
            "bom_edges": self.bom_edges,
            "supplier_item_map": self.supplier_item_map,
            "part_alternatives": self.part_alternatives,
            "incident_events": self.incident_events,
        }
        optional_tables = {
            "supplier_materials": self.supplier_materials,
            "supplier_production_plan": self.supplier_production_plan,
            "supplier_licensed_supply": self.supplier_licensed_supply,
            "supplier_potential_supply": self.supplier_potential_supply,
            "supplier_daily_inventory": self.supplier_daily_inventory,
            "supplier_material_flow_events": self.supplier_material_flow_events,
            "supplier_material_inventory_policy": self.supplier_material_inventory_policy,
        }
        tables.update({name: frame for name, frame in optional_tables.items() if not frame.empty})
        return tables


@dataclass(slots=True)
class ValidationIssue:
    level: str
    check: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)

    def add(self, level: str, check: str, message: str, **details: Any) -> None:
        self.issues.append(
            ValidationIssue(level=level, check=check, message=message, details=details)
        )

    def to_frame(self) -> pd.DataFrame:
        if not self.issues:
            return pd.DataFrame(columns=["level", "check", "message", "details"])
        return pd.DataFrame(
            [
                {
                    "level": issue.level,
                    "check": issue.check,
                    "message": issue.message,
                    "details": issue.details,
                }
                for issue in self.issues
            ]
        )


@dataclass(slots=True)
class ScenarioSpec:
    scenario_id: str
    scenario_type: str
    target_type: str
    target_id: str
    start_date: pd.Timestamp
    duration_days: int
    severity: float = 1.0
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicySpec:
    policy_type: str
    enabled: bool = True
    switch_time_days: int = 0
    priority_rule: str = "share_desc"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SimulationParams:
    time_step: str = "day"
    horizon_days: int = 90
    inventory_buffer_rule: str = "consume_then_stockout"
    record_item_history: bool = True
    target_final_product_id: str | None = None
    enable_supply_tracking: bool = True
    enable_demand_tracking: bool = True
    enable_fusion_tracking: bool = True
    track_network_state: bool = True
    demand_backlog_threshold: float = 0.95
    demand_lost_threshold: float = 0.5
    backlog_retention_ratio: float = 0.8
    fusion_failure_supply_states: tuple[str, ...] = ("unavailable", "blocked")
    fusion_failure_demand_states: tuple[str, ...] = ("lost",)
    fusion_affected_supply_states: tuple[str, ...] = ("degraded",)
    fusion_affected_demand_states: tuple[str, ...] = ("backlog",)
    priority_repair_enabled: bool = True
    priority_repair_lead_days: int = 5
    priority_repair_max_parallel: int = 1
    priority_repair_rule: str = "supplier_impact"
    priority_repair_key_node_bonus_weight: float = 3.0
    mode: str = "bayesian"
    bayesian_enabled: bool = True
    bayesian_use_sampling: bool = False
    bayesian_random_seed: int = 42
    bayesian_config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelBundle:
    standard_bundle: StandardBundle
    supplier_graph: Any
    bom_graph: Any
    supply_map: Any


@dataclass(slots=True)
class SimulationResult:
    scenario: ScenarioSpec
    history: pd.DataFrame
    item_history: pd.DataFrame
    summary: dict[str, Any]
    impacted_paths: list[dict[str, Any]]
    model_bundle: ModelBundle | None = None
    initial_snapshot: dict[str, Any] | None = None
    network_snapshots: list[dict[str, Any]] = field(default_factory=list)
    policy_events: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ReportArtifacts:
    output_dir: Path
    history_csv: Path
    policy_events_csv: Path
    figure_path: Path
    item_history_csv: Path | None = None
    bom_figure_path: Path | None = None
    demand_figure_path: Path | None = None
    timeline_figure_path: Path | None = None
    policy_comparison_summary_csv: Path | None = None
    policy_comparison_time_series_csv: Path | None = None
    policy_comparison_figure_path: Path | None = None
    parameter_experiment_summary_csv: Path | None = None
    parameter_sensitivity_ranking_csv: Path | None = None
    parameter_sensitivity_figure_path: Path | None = None
    monthly_disrupted_nodes_figure_path: Path | None = None
    propagation_duration_figure_path: Path | None = None
    tables_dir: Path | None = None
    figures_dir: Path | None = None
    summary_csv: Path | None = None
    supply_history_csv: Path | None = None
    demand_history_csv: Path | None = None
    fusion_history_csv: Path | None = None
    network_history_csv: Path | None = None
    impacted_paths_csv: Path | None = None
    impact_figure_path: Path | None = None
    core_trends_figure_path: Path | None = None
    supplier_network_figure_path: Path | None = None
    material_network_figure_path: Path | None = None
    frontend_tables_dir: Path | None = None
    frontend_manifest_csv: Path | None = None
    network_snapshot_dir: Path | None = None
    network_snapshot_paths: list[Path] = field(default_factory=list)


@dataclass(slots=True)
class BatchReportArtifacts:
    output_dir: Path
    summary_csv: Path
    tables_dir: Path | None = None
    figures_dir: Path | None = None
    network_comparison_csv: Path | None = None
    scenario_summary_csv: Path | None = None
    policy_summary_csv: Path | None = None
    comparison_figure_path: Path | None = None
    scenario_figure_path: Path | None = None
    timeline_comparison_figure_path: Path | None = None
    supplier_network_comparison_figure_path: Path | None = None
    material_network_comparison_figure_path: Path | None = None
    monthly_disrupted_nodes_comparison_figure_path: Path | None = None
    propagation_duration_comparison_figure_path: Path | None = None
    paper_scenario_policy_csv: Path | None = None
    paper_policy_effect_csv: Path | None = None
    paper_policy_ranking_csv: Path | None = None
    paper_parameter_dimension_csv: Path | None = None
    paper_tradeoff_figure_path: Path | None = None
    paper_summary_figure_path: Path | None = None
