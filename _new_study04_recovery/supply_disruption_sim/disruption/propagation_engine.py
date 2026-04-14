from __future__ import annotations

import pandas as pd

from supply_disruption_sim.model.state_model import SimState
from supply_disruption_sim.disruption.supply_propagation import (
    propagate_supply_to_bom,
    propagate_supply_to_items,
    update_supplier_supply_statuses,
)
from supply_disruption_sim.types import ModelBundle


def update_supplier_statuses(state: SimState, context: dict, model: ModelBundle) -> dict[str, float]:
    return update_supplier_supply_statuses(state=state, context=context, model=model)


def compute_item_supply_statuses(
    current_date: pd.Timestamp,
    state: SimState,
    model: ModelBundle,
    supplier_capacity_factors: dict[str, float],
    context: dict,
    apply_inventory_update: bool = True,
    bayes_engine=None,
) -> None:
    propagate_supply_to_items(
        current_date=current_date,
        state=state,
        model=model,
        supplier_capacity_factors=supplier_capacity_factors,
        context=context,
        apply_inventory_update=apply_inventory_update,
        bayes_engine=bayes_engine,
    )


def propagate_bom_statuses(state: SimState, model: ModelBundle) -> None:
    propagate_supply_to_bom(state=state, model=model)
