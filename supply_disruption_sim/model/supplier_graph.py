from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import pandas as pd


@dataclass(slots=True)
class SupplierGraph:
    graph: nx.DiGraph
    suppliers: pd.DataFrame
    incidents: pd.DataFrame

    @classmethod
    def from_frames(
        cls,
        suppliers: pd.DataFrame,
        supplier_edges: pd.DataFrame,
        incidents: pd.DataFrame,
    ) -> "SupplierGraph":
        graph = nx.DiGraph()
        for row in suppliers.itertuples(index=False):
            graph.add_node(
                row.supplier_id,
                region_id=row.region_id,
                risk_level=row.risk_level,
                incident_count=row.historical_incident_count,
            )
        for row in supplier_edges.itertuples(index=False):
            graph.add_edge(row.source_supplier_id, row.target_supplier_id, relation_type=row.relation_type)
        return cls(graph=graph, suppliers=suppliers.copy(), incidents=incidents.copy())

    def suppliers_in_region(self, region_id: str) -> list[str]:
        return self.suppliers.loc[self.suppliers["region_id"] == region_id, "supplier_id"].tolist()

    def neighbors(self, supplier_id: str) -> list[str]:
        if supplier_id not in self.graph:
            return []
        return list(self.graph.successors(supplier_id))

    def incident_history(self, supplier_id: str) -> pd.DataFrame:
        return self.incidents.loc[self.incidents["supplier_id"] == supplier_id].copy()
