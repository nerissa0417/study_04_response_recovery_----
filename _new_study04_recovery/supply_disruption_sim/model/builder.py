from __future__ import annotations

from supply_disruption_sim.model.bom_graph import BOMGraph
from supply_disruption_sim.model.mapping_graph import SupplyMap
from supply_disruption_sim.model.supplier_graph import SupplierGraph
from supply_disruption_sim.types import ModelBundle, StandardBundle


def build_model(bundle: StandardBundle) -> ModelBundle:
    supplier_graph = SupplierGraph.from_frames(
        suppliers=bundle.suppliers,
        supplier_edges=bundle.supplier_edges,
        incidents=bundle.incident_events,
    )
    bom_graph = BOMGraph.from_frames(items=bundle.items, bom_edges=bundle.bom_edges)
    supply_map = SupplyMap.from_frames(
        supply_map=bundle.supplier_item_map,
        part_alternatives=bundle.part_alternatives,
    )
    return ModelBundle(
        standard_bundle=bundle,
        supplier_graph=supplier_graph,
        bom_graph=bom_graph,
        supply_map=supply_map,
    )
