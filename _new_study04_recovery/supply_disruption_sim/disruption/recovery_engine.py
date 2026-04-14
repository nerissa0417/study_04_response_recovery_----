from __future__ import annotations

import copy

from supply_disruption_sim.disruption.demand_propagation import propagate_demand
from supply_disruption_sim.disruption.fusion_engine import fuse_supply_and_demand
from supply_disruption_sim.disruption.metrics import (
    build_daily_record,
    build_item_records,
    build_simulation_result,
)
from supply_disruption_sim.disruption.propagation_engine import (
    compute_item_supply_statuses,
    propagate_bom_statuses,
    update_supplier_statuses,
)
from supply_disruption_sim.disruption.scenario_injector import inject_scenario_for_day
from supply_disruption_sim.model.state_model import initialize_state
from supply_disruption_sim.policy.policy_manager import PolicyManager
from supply_disruption_sim.policy.priority_repair import override_context_with_repairs
from supply_disruption_sim.probabilistic import BayesianEngine
from supply_disruption_sim.types import ModelBundle, PolicySpec, ScenarioSpec, SimulationParams, SimulationResult


def run_simulation(
    model: ModelBundle,
    scenario: ScenarioSpec,
    policies: list[PolicySpec],
    params: SimulationParams,
) -> SimulationResult:
    state = initialize_state(
        model=model,
        scenario=scenario,
        params=params,
    )
    policy_manager = PolicyManager(policies)
    history_records: list[dict] = []
    item_records: list[dict] = []
    network_snapshots: list[dict] = []
    bayes = None
    if params.bayesian_enabled or params.mode == "bayesian":
        bayes = BayesianEngine(
            config=params.bayesian_config,
            use_sampling=params.bayesian_use_sampling,
            random_seed=params.bayesian_random_seed,
        )

    for current_date in state.timeline:
        context = inject_scenario_for_day(current_date=current_date, scenario=scenario, model=model)
        if bayes is not None:
            context = bayes.apply_supplier_network_propagation(
                current_date=current_date,
                state=state,
                model=model,
                context=context,
                scenario=scenario,
            )
        policy_manager.apply_pre(current_date=current_date, state=state, model=model, context=context)
        context = override_context_with_repairs(context=context, state=state)
        supplier_capacity_factors = update_supplier_statuses(state=state, context=context, model=model)
        compute_item_supply_statuses(
            current_date=current_date,
            state=state,
            model=model,
            supplier_capacity_factors=supplier_capacity_factors,
            context=context,
            apply_inventory_update=True,
            bayes_engine=bayes,
        )
        policy_manager.apply_post(current_date=current_date, state=state, model=model)
        context = override_context_with_repairs(context=context, state=state)
        supplier_capacity_factors = update_supplier_statuses(state=state, context=context, model=model)
        compute_item_supply_statuses(
            current_date=current_date,
            state=state,
            model=model,
            supplier_capacity_factors=supplier_capacity_factors,
            context=context,
            apply_inventory_update=False,
            bayes_engine=bayes,
        )
        propagate_bom_statuses(state=state, model=model)
        propagate_demand(current_date=current_date, state=state, model=model)
        fuse_supply_and_demand(state=state, model=model)

        history_records.append(build_daily_record(current_date=current_date, state=state, model=model))
        if params.record_item_history:
            item_records.extend(build_item_records(current_date=current_date, state=state, model=model))
        if params.track_network_state:
            network_snapshots.append(
                {
                    "date": current_date,
                    "node_state": copy.deepcopy(state.node_state),
                    "edge_state": copy.deepcopy(state.edge_state),
                }
            )

    result = build_simulation_result(
        scenario=scenario,
        history_records=history_records,
        item_records=item_records,
        model=model,
        policy_events=copy.deepcopy(state.policy_event_log),
    )
    result.network_snapshots = network_snapshots
    return result
