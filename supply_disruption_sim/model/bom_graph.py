from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import pandas as pd


@dataclass(slots=True)
class BOMGraph:
    graph: nx.DiGraph
    items: pd.DataFrame
    bom_edges: pd.DataFrame
    parent_to_children: dict[str, list[str]]

    @classmethod
    def from_frames(cls, items: pd.DataFrame, bom_edges: pd.DataFrame) -> "BOMGraph":
        graph = nx.DiGraph()
        parent_to_children: dict[str, list[str]] = {}
        for row in bom_edges.itertuples(index=False):
            graph.add_edge(row.child_item_id, row.parent_item_id, quantity=row.quantity)
            parent_to_children.setdefault(row.parent_item_id, []).append(row.child_item_id)
        for item_id in items["item_id"]:
            graph.add_node(item_id)
        return cls(graph=graph, items=items.copy(), bom_edges=bom_edges.copy(), parent_to_children=parent_to_children)

    def final_products(self) -> list[str]:
        return self.items.loc[self.items["is_final_product"], "item_id"].tolist()

    def ancestors_of(self, item_id: str) -> list[str]:
        if item_id not in self.graph:
            return []
        return sorted(nx.ancestors(self.graph, item_id))

    def descendants_of(self, item_id: str) -> list[str]:
        if item_id not in self.graph:
            return []
        return sorted(nx.descendants(self.graph.reverse(copy=False), item_id))

    def children_of(self, parent_item_id: str) -> list[str]:
        return list(self.parent_to_children.get(parent_item_id, []))

    def child_first_order(self) -> list[str]:
        return list(nx.topological_sort(self.graph))

    def paths_to_final_products(self, item_id: str) -> list[list[str]]:
        paths: list[list[str]] = []
        for final_product in self.final_products():
            if item_id in self.graph and final_product in self.graph and nx.has_path(self.graph, item_id, final_product):
                paths.extend(nx.all_simple_paths(self.graph, item_id, final_product))
        return paths
