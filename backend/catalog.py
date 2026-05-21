from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class CatalogMaterial:
    id: str
    name: str
    unit: str
    unit_price: float


@dataclass(frozen=True)
class CatalogItem:
    id: str
    name: str
    category: str
    price: float
    material_ids: Tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    currency: str
    materials_by_id: Dict[str, CatalogMaterial]
    items_by_id: Dict[str, CatalogItem]

    def items_list(self) -> List[CatalogItem]:
        return list(self.items_by_id.values())

    def materials_list(self) -> List[CatalogMaterial]:
        return list(self.materials_by_id.values())


def load_catalog() -> Catalog:
    """
    Loads `backend/catalog.json`.
    Kept local and deterministic so the model can be constrained to known SKUs.
    """
    path = Path(__file__).with_name("catalog.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    currency = str(raw.get("currency") or "INR").strip() or "INR"

    mats: Dict[str, CatalogMaterial] = {}
    for m in raw.get("materials", []):
        mat = CatalogMaterial(
            id=str(m["id"]),
            name=str(m["name"]),
            unit=str(m["unit"]),
            unit_price=float(m["unit_price"]),
        )
        mats[mat.id] = mat

    items: Dict[str, CatalogItem] = {}
    for it in raw.get("items", []):
        item = CatalogItem(
            id=str(it["id"]),
            name=str(it["name"]),
            category=str(it.get("category", "")),
            price=float(it["price"]),
            material_ids=tuple(str(x) for x in (it.get("material_ids") or [])),
        )
        items[item.id] = item

    return Catalog(currency=currency, materials_by_id=mats, items_by_id=items)

