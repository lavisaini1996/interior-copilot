"""
Heuristic wall-space checks for furniture vs doors/windows and room dimensions.
Used by the API and mirrored in the frontend for instant feedback.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

WALL_IDS = ("north", "south", "east", "west")

# Approximate metres of wall run required along the wall (queen bed, standard modules).
ITEM_WALL_SPACE_M: Dict[str, float] = {
    "bed": 1.65,
    "headboard": 0.0,
    "wardrobe": 1.85,
    "loft": 1.2,
    "bedside": 0.55,
    "dresser": 1.25,
    "chest_of_drawers": 0.9,
    "tv_unit": 1.6,
    "study": 1.2,
    "desk": 1.2,
    "wall_desk": 1.0,
    "reading_chair": 0.85,
    "bench": 1.2,
    "mirror": 0.5,
    "wall_sconces": 0.0,
    "art": 0.0,
    "planter": 0.45,
    "accent_wall": 0.0,
    "wallpaper": 0.0,
    "sofa": 2.1,
    "sectional": 2.6,
    "accent_chair": 0.85,
    "ottoman": 0.7,
    "coffee_table": 1.1,
    "side_table": 0.5,
    "console": 1.2,
    "bookshelf": 1.0,
    "sideboard": 1.5,
    "bar_cabinet": 1.0,
    "floor_lamp": 0.4,
    "fireplace": 1.2,
    "base_cabinets": 2.4,
    "wall_cabinets": 0.0,
    "tall_unit": 0.65,
    "hob": 0.6,
    "chimney": 0.0,
    "oven": 0.6,
    "microwave": 0.5,
    "sink": 0.8,
    "dishwasher": 0.6,
    "fridge": 0.7,
    "counter": 1.5,
    "peninsula": 1.4,
    "backsplash": 0.0,
    "open_shelving": 1.0,
    "water_purifier": 0.35,
    "vanity": 1.2,
    "wc": 0.7,
    "wall_wc": 0.55,
    "shower": 0.9,
    "bathtub": 1.7,
    "linen": 0.6,
    "niche": 0.0,
    "towel_rack": 0.0,
    "glass_partition": 0.0,
    "wall_tile_feature": 0.0,
    "dining_table": 1.6,
    "dining_chairs": 0.0,
    "crockery": 1.2,
    "wine_rack": 0.6,
    "pendant_light": 0.0,
    "walkin": 2.2,
    "shoe": 0.9,
    "jewelry_safe": 0.0,
    "drawers": 0.0,
    "rod": 0.0,
    "filing": 0.5,
    "pegboard": 0.0,
    "pooja_unit": 1.0,
    "jali": 0.0,
    "storage": 0.8,
    "wall_paneling": 0.0,
    "lighting": 0.0,
    "coat_hooks": 0.0,
    "vertical_garden": 0.0,
    "seating": 1.2,
    "cafe_table": 0.9,
    "swing": 1.4,
    "deck_floor": 0.0,
    "washing_machine": 0.65,
    "dryer": 0.65,
    "drying_rack": 0.8,
    "storage_cabinets": 1.2,
    "iron_board": 0.0,
    "chair": 0.75,
}

DEFAULT_NS_WALL_M = 3.6
DEFAULT_EW_WALL_M = 4.2
ITEM_CLEARANCE_M = 0.25
MIN_USABLE_AFTER_OPENINGS_M = 0.9

_WALL_LABELS = {"north": "North", "south": "South", "east": "East", "west": "West"}


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def wall_length_m(brief: Dict[str, Any], wall_id: str) -> float:
    """North/south walls span room width; east/west span room length."""
    ln = _num(brief.get("room_length_m"))
    wd = _num(brief.get("room_width_m"))
    if wall_id in ("north", "south"):
        return wd if wd is not None else DEFAULT_NS_WALL_M
    return ln if ln is not None else DEFAULT_EW_WALL_M


def opening_usage_m(openings: List[str]) -> Tuple[float, bool]:
    """Returns (metres consumed along wall, blocks_all_furniture)."""
    total = 0.0
    blocks_all = False
    for raw in openings:
        op = str(raw).strip().lower()
        if not op:
            continue
        if any(k in op for k in ("full-height", "full height", "glazing wall", "curtain wall", "entire wall")):
            return 999.0, True
        if "double door" in op or "double-door" in op:
            total += 1.6
        elif "door" in op:
            total += 0.95
        elif "slider" in op or "sliding" in op or "folding" in op:
            total += 1.55
        elif "window" in op or "glazing" in op:
            total += 1.2
        elif "opening" in op or "arch" in op:
            total += 0.85
        else:
            total += 0.75
    return total, blocks_all


def items_usage_m(item_ids: List[str]) -> float:
    total = 0.0
    for iid in item_ids:
        key = str(iid).strip()
        if not key:
            continue
        space = ITEM_WALL_SPACE_M.get(key, 0.7)
        if space > 0:
            total += space + ITEM_CLEARANCE_M
    return total


def can_place_on_wall(
    *,
    brief: Dict[str, Any],
    wall_id: str,
    item_id: str,
    assignments: Dict[str, List[str]],
    openings: Dict[str, List[str]],
) -> Tuple[bool, str]:
    wall_name = _WALL_LABELS.get(wall_id, wall_id)
    item_space = ITEM_WALL_SPACE_M.get(item_id, 0.7)
    if item_space <= 0:
        return True, ""

    wall_len = wall_length_m(brief, wall_id)
    wall_ops = openings.get(wall_id) or []
    if not isinstance(wall_ops, list):
        wall_ops = []

    op_use, blocks_all = opening_usage_m([str(x) for x in wall_ops if x])
    if blocks_all:
        return (
            False,
            f"Cannot place on the {wall_name} wall: openings (e.g. full-height glazing) use the full wall. "
            f"Try another wall or remove an opening from the plan read.",
        )

    current = assignments.get(wall_id) or []
    if not isinstance(current, list):
        current = []
    if item_id in current:
        return True, ""

    used_items = items_usage_m([str(x) for x in current if isinstance(x, str)])
    needed = item_space + ITEM_CLEARANCE_M
    available = wall_len - op_use - used_items

    if available < needed:
        op_note = ""
        if wall_ops:
            op_note = f" Doors/windows on this wall need ~{op_use:.1f} m. "
        dim_note = ""
        ln = _num(brief.get("room_length_m"))
        wd = _num(brief.get("room_width_m"))
        if ln and wd:
            dim_note = f" Wall length ~{wall_len:.1f} m ({'width' if wall_id in ('north', 'south') else 'length'} of room)."
        else:
            dim_note = f" Estimated wall length ~{wall_len:.1f} m (upload plan dimensions for accuracy)."
        return (
            False,
            f"Not enough space on the {wall_name} wall for this item (~{needed:.1f} m needed, ~{max(0, available):.1f} m free)."
            + op_note
            + dim_note
            + " Try another wall or fewer items on this wall.",
        )

    if op_use > 0 and available < needed + MIN_USABLE_AFTER_OPENINGS_M:
        return (
            False,
            f"The {wall_name} wall is too tight next to doors/windows. "
            f"Choose a wall with more clear run or shift openings in your plan.",
        )

    return True, ""


def format_placement_verification(brief: Dict[str, Any]) -> str:
    """Human-readable compass map for design rationales and UI."""
    assignments = brief.get("wall_assignments") or {}
    openings = brief.get("wall_openings") or {}
    if not isinstance(assignments, dict):
        assignments = {}
    if not isinstance(openings, dict):
        openings = {}

    def label_for(v: str) -> str:
        return str(v).replace("_", " ")

    lines: List[str] = [
        "Compass placement (verify in image — N/S/E/W):",
    ]
    north_deg = brief.get("floorplan_north_clockwise_deg")
    if north_deg is not None:
        try:
            lines.append(f"  Plan north: {float(north_deg) % 360:.0f}° clockwise from top of floor-plan image.")
        except (TypeError, ValueError):
            pass

    for wid, wname in [("north", "North"), ("south", "South"), ("east", "East"), ("west", "West")]:
        items = assignments.get(wid) or []
        ops = openings.get(wid) or []
        item_txt = ", ".join(label_for(x) for x in items if isinstance(x, str) and str(x).strip()) or "—"
        op_txt = "; ".join(str(x).strip() for x in ops if isinstance(x, str) and str(x).strip()) or "none"
        lines.append(f"  {wname} wall — Furniture: {item_txt} | Openings: {op_txt}")

    ln = _num(brief.get("room_length_m"))
    wd = _num(brief.get("room_width_m"))
    if ln and wd:
        lines.append(f"  Room size: {ln:.2f} m (N↔S) × {wd:.2f} m (E↔W).")

    return "\n".join(lines)


def enhance_image_prompt_for_compass(prompt: str, brief: Dict[str, Any]) -> str:
    """Append compass / placement cues for image generation."""
    assignments = brief.get("wall_assignments") or {}
    if not isinstance(assignments, dict):
        return prompt
    has_any = any(isinstance(assignments.get(w), list) and assignments.get(w) for w in WALL_IDS)
    if not has_any:
        return prompt
    extra = (
        " Include a small compass-rose graphic in one corner (shape only — no N/S/E/W letters on the image). "
        "Do not obscure furniture. State wall directions in the description only: name each major catalog item with "
        "its compass wall (NORTH/SOUTH/EAST/WEST) in the rationale, not as labels on the compass graphic."
    )
    if extra.strip() in prompt:
        return prompt
    return (prompt.rstrip() + extra).strip()
