from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(slots=True)
class SupplyMap:
    supply_map: pd.DataFrame
    part_alternatives: pd.DataFrame

    @classmethod
    def from_frames(cls, supply_map: pd.DataFrame, part_alternatives: pd.DataFrame) -> "SupplyMap":
        return cls(supply_map=supply_map.copy(), part_alternatives=part_alternatives.copy())

    def item_rows(self, item_id: str) -> pd.DataFrame:
        return self.supply_map.loc[self.supply_map["item_id"] == item_id].copy()

    def primary_rows(self, item_id: str) -> pd.DataFrame:
        return self.supply_map.loc[
            (self.supply_map["item_id"] == item_id) & (self.supply_map["is_primary"])
        ].copy()

    def backup_rows(self, item_id: str) -> pd.DataFrame:
        return self.supply_map.loc[
            (self.supply_map["item_id"] == item_id) & (self.supply_map["is_backup"])
        ].copy()

    def supplied_items(self, supplier_id: str) -> list[str]:
        return self.supply_map.loc[self.supply_map["supplier_id"] == supplier_id, "item_id"].tolist()

    def alternative_items(self, item_id: str) -> list[str]:
        rows = self.part_alternatives.loc[self.part_alternatives["item_id"] == item_id]
        return rows.sort_values("priority")["alt_item_id"].tolist()
