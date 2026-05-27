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

DEFAULT_NS_WALL_M = 3.4
DEFAULT_EW_WALL_M = 3.8
ITEM_CLEARANCE_M = 0.25
MIN_USABLE_AFTER_OPENINGS_M = 0.9
MIN_WALL_M = 2.4
MAX_WALL_M = 14.0
FT_TO_M = 0.3048

# Must be placeable in primary room types (e.g. bed in bedroom).
ESSENTIAL_ITEMS_BY_ROOM: Dict[str, frozenset[str]] = {
    "bedroom": frozenset({"bed"}),
    "living": frozenset({"sofa", "sectional"}),
    "kitchen": frozenset({"base_cabinets", "sink"}),
    "dining": frozenset({"dining_table"}),
    "bathroom": frozenset({"wc", "wall_wc", "vanity"}),
    "study": frozenset({"desk", "study"}),
}

_WALL_LABELS = {"north": "North", "south": "South", "east": "East", "west": "West"}

# Human-readable labels for wall-picker tokens (shared with API formatters).
WALL_ITEM_LABELS: Dict[str, str] = {
    "bed": "bed",
    "headboard": "upholstered headboard",
    "wardrobe": "wardrobe",
    "loft": "loft storage",
    "bedside": "bedside table",
    "dresser": "dresser",
    "chest_of_drawers": "chest of drawers",
    "tv_unit": "TV unit",
    "study": "study desk",
    "desk": "desk",
    "wall_desk": "wall-mounted desk",
    "chair": "office chair",
    "reading_chair": "reading chair",
    "bench": "bench",
    "mirror": "mirror",
    "wall_sconces": "wall sconces",
    "art": "art / wall decor",
    "planter": "planter",
    "accent_wall": "accent wall / paneling",
    "wallpaper": "wallpaper feature",
    "sofa": "sofa",
    "sectional": "sectional sofa",
    "accent_chair": "accent chair",
    "ottoman": "ottoman",
    "coffee_table": "coffee table",
    "side_table": "side table",
    "console": "console",
    "bookshelf": "bookshelf",
    "sideboard": "sideboard / buffet",
    "bar_cabinet": "bar cabinet",
    "floor_lamp": "floor lamp",
    "fireplace": "fireplace",
    "base_cabinets": "base cabinets",
    "wall_cabinets": "wall / upper cabinets",
    "tall_unit": "tall unit / pantry",
    "hob": "hob / cooktop",
    "chimney": "chimney / hood",
    "oven": "built-in oven",
    "microwave": "microwave nook",
    "sink": "sink",
    "dishwasher": "dishwasher",
    "fridge": "fridge",
    "counter": "breakfast counter",
    "peninsula": "peninsula",
    "backsplash": "backsplash",
    "open_shelving": "open shelving",
    "water_purifier": "water purifier",
    "vanity": "vanity / counter",
    "wc": "WC",
    "wall_wc": "wall-hung WC",
    "shower": "shower / enclosure",
    "bathtub": "bathtub",
    "linen": "linen cupboard",
    "niche": "recessed niche",
    "towel_rack": "towel rack",
    "glass_partition": "glass partition",
    "wall_tile_feature": "feature wall tile",
    "dining_table": "dining table",
    "dining_chairs": "dining chairs",
    "crockery": "crockery unit",
    "wine_rack": "wine rack",
    "pendant_light": "pendant light(s)",
    "walkin": "walk-in wardrobe",
    "shoe": "shoe storage",
    "jewelry_safe": "jewelry / safe drawer",
    "drawers": "pull-out drawers",
    "rod": "hanging rod section",
    "filing": "filing cabinet",
    "pegboard": "pegboard",
    "pooja_unit": "pooja unit / mandir",
    "jali": "jali / lattice screen",
    "storage": "drawer storage",
    "wall_paneling": "wood paneling",
    "lighting": "cove / spot lighting",
    "coat_hooks": "coat hooks",
    "vertical_garden": "vertical garden",
    "seating": "seating bench",
    "cafe_table": "café table",
    "swing": "swing / jhoola",
    "deck_floor": "deck flooring",
    "washing_machine": "washing machine",
    "dryer": "dryer",
    "drying_rack": "drying rack",
    "storage_cabinets": "storage cabinets",
    "iron_board": "iron / fold-out board",
}


def _item_label(item_id: str) -> str:
    key = str(item_id).strip()
    return WALL_ITEM_LABELS.get(key, key.replace("_", " "))


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def normalize_dims_to_metres(
    length_m: float | None, width_m: float | None
) -> Tuple[float | None, float | None]:
    """Plans labelled length_m may still be in feet (e.g. 10' x 12' bedroom)."""
    if length_m is None or width_m is None:
        return length_m, width_m
    mx = max(length_m, width_m)
    mn = min(length_m, width_m)
    area = length_m * width_m
    if mx <= 6.5:
        return length_m, width_m
    if 8.0 <= mx <= 30.0 and 5.0 <= mn <= 22.0 and 70.0 <= area <= 650.0:
        return round(length_m * FT_TO_M, 3), round(width_m * FT_TO_M, 3)
    return length_m, width_m


def _room_kind_from_brief(brief: Dict[str, Any]) -> str:
    label = str(brief.get("selected_room_name") or brief.get("space_type") or "").lower()
    if "bed" in label:
        return "bedroom"
    if "kitchen" in label:
        return "kitchen"
    if "living" in label or "lounge" in label:
        return "living"
    if "dining" in label:
        return "dining"
    if "bath" in label or "toilet" in label or "wc" in label:
        return "bathroom"
    if "study" in label or "office" in label:
        return "study"
    return "bedroom"


def _is_essential_item(brief: Dict[str, Any], item_id: str) -> bool:
    kind = _room_kind_from_brief(brief)
    return item_id in ESSENTIAL_ITEMS_BY_ROOM.get(kind, frozenset())


def _room_dims_from_brief(brief: Dict[str, Any]) -> Tuple[float | None, float | None]:
    ln = _num(brief.get("room_length_m"))
    wd = _num(brief.get("room_width_m"))
    rid = brief.get("selected_room_id")
    rooms = brief.get("rooms_detected") or []
    if isinstance(rid, str) and rid.strip() and isinstance(rooms, list):
        sid = rid.strip()
        for r in rooms:
            if not isinstance(r, dict):
                continue
            if str(r.get("id") or "").strip() != sid:
                continue
            rln = _num(r.get("length_m"))
            rwd = _num(r.get("width_m"))
            if rln is not None and rwd is not None:
                return normalize_dims_to_metres(rln, rwd)
            break
    if ln is not None and wd is not None:
        return normalize_dims_to_metres(ln, wd)
    return ln, wd


def wall_length_m(brief: Dict[str, Any], wall_id: str) -> float:
    """North/south walls span room width; east/west span room length."""
    ln, wd = _room_dims_from_brief(brief)
    openings = brief.get("wall_openings") or {}
    if not isinstance(openings, dict):
        openings = {}
    ops = openings.get(wall_id) or []
    has_ops = isinstance(ops, list) and len(ops) > 0

    if wall_id in ("north", "south"):
        run = wd if wd is not None else (DEFAULT_NS_WALL_M - 0.4 if has_ops else DEFAULT_NS_WALL_M)
    else:
        run = ln if ln is not None else (DEFAULT_EW_WALL_M - 0.4 if has_ops else DEFAULT_EW_WALL_M)
    return min(MAX_WALL_M, max(MIN_WALL_M, float(run)))


def opening_usage_m(openings: List[str], *, wall_len: float | None = None) -> Tuple[float, bool]:
    """Returns (metres consumed along wall for furniture layout, blocks_all_furniture)."""
    total = 0.0
    blocks_all = False
    for raw in openings:
        op = str(raw).strip().lower()
        if not op:
            continue
        if any(k in op for k in ("full-height", "full height", "curtain wall", "entire wall")):
            return 999.0, True
        if "glazing wall" in op and "window" not in op:
            return 999.0, True
        if "double door" in op or "double-door" in op:
            total += 1.45
        elif "door" in op:
            total += 0.85
        elif "slider" in op or "sliding" in op or "folding" in op:
            total += 1.35
        elif "window" in op:
            total += 0.5
        elif "glazing" in op:
            total += 0.55
        elif "opening" in op or "arch" in op:
            total += 0.75
        else:
            total += 0.65
    if wall_len is not None and wall_len > 0 and total > wall_len * 0.55:
        total = wall_len * 0.55
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

    essential = _is_essential_item(brief, item_id)
    op_use, blocks_all = opening_usage_m([str(x) for x in wall_ops if x], wall_len=wall_len)
    if blocks_all and not essential:
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
    clearance = 0.15 if essential else ITEM_CLEARANCE_M
    needed = item_space + clearance
    available = wall_len - op_use - used_items

    if essential and not blocks_all:
        min_run = min(item_space + 0.1, 1.35)
        if available >= min_run:
            return True, ""

    if available < needed:
        op_note = ""
        if wall_ops:
            op_note = f" Doors/windows on this wall need ~{op_use:.1f} m. "
        dim_note = ""
        ln, wd = _room_dims_from_brief(brief)
        if ln is not None and wd is not None:
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

    if (
        not essential
        and op_use > 0
        and available < needed + MIN_USABLE_AFTER_OPENINGS_M
    ):
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
        return _item_label(v)

    lines: List[str] = [
        "Compass placement (N/S/E/W):",
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

    ln, wd = _room_dims_from_brief(brief)
    if ln is not None and wd is not None:
        lines.append(f"  Room size: {ln:.2f} m (N↔S) × {wd:.2f} m (E↔W).")

    return "\n".join(lines)


def _has_wall_layout_data(brief: Dict[str, Any]) -> bool:
    assignments = brief.get("wall_assignments") or {}
    openings = brief.get("wall_openings") or {}
    if not isinstance(assignments, dict):
        assignments = {}
    if not isinstance(openings, dict):
        openings = {}
    has_items = any(isinstance(assignments.get(w), list) and assignments.get(w) for w in WALL_IDS)
    has_ops = any(isinstance(openings.get(w), list) and openings.get(w) for w in WALL_IDS)
    return has_items or has_ops


# Where each compass wall appears in the photograph for a fixed corner camera.
_FRAME_WALL_POSITION: Dict[str, Dict[str, str]] = {
    "sw_ne": {
        "north": "far/back wall across the frame",
        "east": "right-hand wall",
        "south": "near/bottom edge at the camera",
        "west": "left-hand wall",
    },
    "west_to_east": {
        "north": "left-hand wall",
        "south": "right-hand wall",
        "east": "far/back wall",
        "west": "near edge at the camera",
    },
    "south_to_north": {
        "east": "right-hand wall",
        "west": "left-hand wall",
        "north": "far/back wall",
        "south": "near edge at the camera",
    },
}


def _camera_pose(brief: Dict[str, Any]) -> str:
    """Pose key used for viewer-centric wall → frame mapping."""
    assignments = brief.get("wall_assignments") or {}
    if not isinstance(assignments, dict):
        assignments = {}
    openings = brief.get("wall_openings") or {}
    if not isinstance(openings, dict):
        openings = {}
    ns = any(
        (assignments.get(w) or openings.get(w))
        for w in ("north", "south")
    )
    ew = any(
        (assignments.get(w) or openings.get(w))
        for w in ("east", "west")
    )
    if ns and ew:
        return "sw_ne"
    if ns:
        return "west_to_east"
    if ew:
        return "south_to_north"
    return "sw_ne"


def build_spatial_frame_block(brief: Dict[str, Any]) -> str:
    """
    Viewer-centric mapping so image models place each wall's furniture/openings
    on the correct physical wall in the photograph (not just in text).
    """
    if not _has_wall_layout_data(brief):
        return ""

    pose = _camera_pose(brief)
    frame = _FRAME_WALL_POSITION.get(pose, _FRAME_WALL_POSITION["sw_ne"])
    assignments = brief.get("wall_assignments") or {}
    openings = brief.get("wall_openings") or {}
    if not isinstance(assignments, dict):
        assignments = {}
    if not isinstance(openings, dict):
        openings = {}

    pose_desc = {
        "sw_ne": "south-west corner, camera aimed toward the north-east corner",
        "west_to_east": "west corner, camera aimed toward the east wall",
        "south_to_north": "south corner, camera aimed toward the north wall",
    }.get(pose, "south-west corner toward north-east")

    lines: List[str] = [
        "PHOTOGRAPH SPATIAL MAP (fixed camera — render walls in these frame positions; do not rotate the room):",
        f"Camera: standing in the {pose_desc}, wide-angle ~24mm, eye height ~1.5 m.",
    ]
    for wid, wname in [("north", "NORTH"), ("south", "SOUTH"), ("east", "EAST"), ("west", "WEST")]:
        where = frame.get(wid, wid)
        lines.append(f"  • {wname} wall appears as the {where} in this shot.")

    checklist: List[str] = []
    for wid, wname in [("north", "NORTH"), ("south", "SOUTH"), ("east", "EAST"), ("west", "WEST")]:
        where = frame.get(wid, wid)
        for item in assignments.get(wid) or []:
            if isinstance(item, str) and str(item).strip():
                checklist.append(
                    f"  • {_item_label(item)} must sit flush on the {wname} wall ({where}), not on any other wall."
                )
        for op in openings.get(wid) or []:
            if isinstance(op, str) and str(op).strip():
                checklist.append(
                    f"  • Opening \"{str(op).strip()}\" must be on the {wname} wall ({where}), matching the floor plan."
                )
    if checklist:
        lines.append("MANDATORY VISIBILITY (every line below must be true in the image):")
        lines.extend(checklist)

    lines.append(
        "Use the attached floor plan to match room shape, door swings, and window positions on these same walls."
    )
    return "\n".join(lines)


def _camera_instruction(brief: Dict[str, Any]) -> str:
    assignments = brief.get("wall_assignments") or {}
    if not isinstance(assignments, dict):
        assignments = {}
    ns = bool(assignments.get("north")) or bool(assignments.get("south"))
    ew = bool(assignments.get("east")) or bool(assignments.get("west"))
    openings = brief.get("wall_openings") or {}
    if isinstance(openings, dict):
        if not ns:
            ns = bool(openings.get("north")) or bool(openings.get("south"))
        if not ew:
            ew = bool(openings.get("east")) or bool(openings.get("west"))
    if ns and ew:
        return (
            "Wide-angle two-point perspective from the south-west corner looking toward the north-east, "
            "~24mm equivalent, so all four walls are partially visible. Do not use a straight-on one-wall shot."
        )
    if ns:
        return (
            "Wide-angle perspective from the east or west corner so BOTH the north and south walls are visible "
            "in the same frame. Furniture on north/south walls must be clearly readable."
        )
    if ew:
        return (
            "Wide-angle perspective from the north or south corner so BOTH the east and west walls are visible "
            "in the same frame. Furniture on east/west walls must be clearly readable."
        )
    return "Wide-angle corner perspective showing at least two walls with correct compass orientation."


def build_layout_ascii_diagram(brief: Dict[str, Any]) -> str:
    """Top-down schematic — helps image models keep N/S/E/W consistent."""
    if not _has_wall_layout_data(brief):
        return ""
    assignments = brief.get("wall_assignments") or {}
    openings = brief.get("wall_openings") or {}
    if not isinstance(assignments, dict):
        assignments = {}
    if not isinstance(openings, dict):
        openings = {}

    def wall_line(wid: str) -> str:
        items = assignments.get(wid) or []
        ops = openings.get(wid) or []
        parts: List[str] = []
        if isinstance(items, list) and items:
            parts.append(", ".join(_item_label(str(x)) for x in items if x))
        if isinstance(ops, list) and ops:
            parts.append("OPEN: " + "; ".join(str(x).strip() for x in ops if str(x).strip()))
        return " | ".join(parts) if parts else "(empty)"

    return (
        "TOP-DOWN ROOM SCHEMATIC (fixed — do not rotate):\n"
        f"        NORTH — {wall_line('north')}\n"
        f"WEST — {wall_line('west')}  |  ROOM  |  EAST — {wall_line('east')}\n"
        f"        SOUTH — {wall_line('south')}"
    )


def build_mandatory_layout_block(brief: Dict[str, Any]) -> str:
    """
    Deterministic layout spec prepended to Imagen prompts so renders follow
    user wall picks and plan-detected openings instead of hallucinating layout.
    """
    if not _has_wall_layout_data(brief):
        return ""

    assignments = brief.get("wall_assignments") or {}
    openings = brief.get("wall_openings") or {}
    if not isinstance(assignments, dict):
        assignments = {}
    if not isinstance(openings, dict):
        openings = {}

    room_name = str(brief.get("selected_room_name") or brief.get("space_type") or "room").strip()
    lines: List[str] = [
        "MANDATORY FLOOR PLAN LAYOUT — follow exactly; do not move furniture or openings to other walls:",
        f"Subject: photorealistic interior of {room_name}.",
    ]

    ln, wd = _room_dims_from_brief(brief)
    ch = _num(brief.get("ceiling_height_m"))
    if ln is not None and wd is not None:
        dim = f"Room size {ln:.2f} m north–south × {wd:.2f} m east–west"
        if ch:
            dim += f", ceiling {ch:.2f} m"
        lines.append(dim + ".")
    elif brief.get("use_floorplan_image_for_scale_only"):
        lines.append("Match proportions of the uploaded floor plan; do not change wall count or door/window positions.")

    north_deg = brief.get("floorplan_north_clockwise_deg")
    if north_deg is not None:
        try:
            lines.append(
                f"Compass: plan north is {float(north_deg) % 360:.0f}° clockwise from the top of the floor-plan sheet; "
                "NORTH wall is the wall that faces geographic north on the plan."
            )
        except (TypeError, ValueError):
            pass

    door_lines: List[str] = []
    for wid, wname in [("north", "NORTH"), ("south", "SOUTH"), ("east", "EAST"), ("west", "WEST")]:
        ops = openings.get(wid) or []
        if not isinstance(ops, list):
            continue
        for op in ops:
            if not isinstance(op, str) or not str(op).strip():
                continue
            phrase = str(op).strip()
            if any(k in phrase.lower() for k in ("door", "hallway", "closet", "balcony", "window", "slider", "glazing")):
                door_lines.append(f"  {wname} wall — {phrase} (show this exact opening in the render)")

    if door_lines:
        lines.append("DOORS/WINDOWS FROM FLOOR PLAN (mandatory — same wall, same destination label):")
        lines.extend(door_lines)

    lines.append("Wall-by-wall furniture (fixed positions):")
    for wid, wname in [("north", "NORTH"), ("south", "SOUTH"), ("east", "EAST"), ("west", "WEST")]:
        items = assignments.get(wid) or []
        item_list = [_item_label(x) for x in items if isinstance(x, str) and str(x).strip()]
        furn = ", ".join(item_list) if item_list else "no furniture"
        lines.append(f"  {wname} wall — furniture: {furn}.")

    lines.append(
        "Rules: (1) Furniture only on its assigned wall. "
        "(2) Every door/window listed above must appear on that compass wall facing the named destination (hallway, closet, etc.). "
        "(3) Do not add, remove, or relocate doors/windows. (4) Do not mirror or rotate the room vs the plan."
    )
    lines.append(f"Camera: {_camera_instruction(brief)}")
    spatial = build_spatial_frame_block(brief)
    if spatial:
        lines.append(spatial)
    ascii_diag = build_layout_ascii_diagram(brief)
    if ascii_diag:
        lines.append(ascii_diag)
    return "\n".join(lines)


def enforce_wall_placement_in_prompt(prompt: str, brief: Dict[str, Any]) -> str:
    """Prepend locked layout block so image models cannot ignore wall assignments."""
    block = build_mandatory_layout_block(brief)
    if not block:
        return prompt.strip()
    if block in prompt:
        return prompt.strip()
    style = (prompt or "").strip() or "Warm minimal interior with catalog furniture and realistic materials."
    return (
        block
        + "\n\nSTYLE AND FINISHES (vary materials/colors only — never change wall positions or openings):\n"
        + style
    ).strip()


_NO_LOGO_IN_IMAGE = (
    "No logo, watermark, brand mark, signature, compass rose, north arrow, text overlay, "
    "UI badge, or corner graphic anywhere in the photograph."
)

_REFINE_IMAGE_QUALITY = (
    "Photorealistic architectural interior photograph: natural daylight, accurate scale and proportions, "
    "realistic materials and shadows, professional staging, sharp focus, no wide-angle distortion of walls. "
    "Every piece of furniture and every door/window must sit on its assigned NORTH/SOUTH/EAST/WEST wall."
)


def enhance_image_prompt_for_compass(prompt: str, brief: Dict[str, Any]) -> str:
    """Final image prompt polish: direction fidelity, quality, no logos/overlays."""
    out = str(prompt or "").strip()
    out = re.sub(
        r"\b(include|add|show|with)\s+(?:a\s+)?(?:small\s+)?compass[- ]?rose[^.]*\.?",
        "",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(r"\bcompass[- ]?rose\s+graphic[^.]*\.?", "", out, flags=re.IGNORECASE)
    if _has_wall_layout_data(brief):
        spatial = build_spatial_frame_block(brief)
        if spatial and "PHOTOGRAPH SPATIAL MAP" not in out:
            out = (out.rstrip() + "\n\n" + spatial).strip()
        wall_note = (
            "Place each catalog item on the compass wall named in the layout — "
            "the physical wall in the photo must match (back/left/right/near as specified). "
            "Do not draw N/S/E/W letters or symbols on the image."
        )
        if wall_note.lower() not in out.lower():
            out = (out.rstrip() + " " + wall_note).strip()
    if _REFINE_IMAGE_QUALITY.lower() not in out.lower():
        out = (out.rstrip() + " " + _REFINE_IMAGE_QUALITY).strip()
    if _NO_LOGO_IN_IMAGE.lower() not in out.lower():
        out = (out.rstrip() + " " + _NO_LOGO_IN_IMAGE).strip()
    return out
