"""Wall-by-wall moodboard planning helpers (Mr Dileep–style panels per wall/zone)."""

from __future__ import annotations

import re
from typing import Any, Dict, List

WALL_ZONE_IDS = ("north", "south", "east", "west")
EXTRA_ZONE_IDS = ("ceiling", "overview", "floor")

# Minimum floor-plane furniture per room type (professional layout standards).
ROOM_FLOOR_STANDARDS: Dict[str, List[str]] = {
    "dining": [
        "dining table sized for the room (typically 6–8 seats)",
        "dining chairs fully around the table",
        "centered rug under the table optional",
    ],
    "living": [
        "coffee table aligned with the seating group",
        "area rug anchoring the seating zone",
        "side table or ottoman as appropriate",
    ],
    "bedroom": [
        "bed on the floor plane (headboard on assigned wall)",
        "bedside tables if room allows",
        "rug at foot or under bed zone",
    ],
    "kitchen": [
        "kitchen island or peninsula if the plan shows one",
        "clear circulation paths on the floor",
        "dining nook table only if shown on the plan",
    ],
    "study": [
        "desk with chair on the floor",
        "rug under desk zone",
    ],
    "bathroom": [
        "clear floor finish only — no loose furniture unless vanity stool shown",
    ],
    "default": [
        "appropriate freestanding furniture for the room type on the floor plane",
        "rug or clear floor treatment matching the style brief",
    ],
}


def normalize_wall_assignments(raw: Any) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {k: [] for k in WALL_ZONE_IDS}
    if not isinstance(raw, dict):
        return out
    for k in WALL_ZONE_IDS:
        v = raw.get(k) or []
        if isinstance(v, list):
            out[k] = [str(x).strip() for x in v if isinstance(x, str) and str(x).strip()]
    return out


def normalize_wall_openings(raw: Any) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {k: [] for k in WALL_ZONE_IDS}
    if not isinstance(raw, dict):
        return out
    for k in WALL_ZONE_IDS:
        v = raw.get(k) or []
        if isinstance(v, list):
            out[k] = [str(x).strip() for x in v if isinstance(x, str) and str(x).strip()]
    return out


def infer_room_kind(brief: Dict[str, Any]) -> str:
    """Map selected room name / space_type to a floor-standards key."""
    text = " ".join(
        str(brief.get(k) or "")
        for k in ("selected_room_name", "space_type", "notes")
    ).lower()
    if re.search(r"\bdining\b", text):
        return "dining"
    if re.search(r"\bliving\b|\bdrawing\b|\bhall\b|\blounge\b", text):
        return "living"
    if re.search(r"\bbed\b|\bbedroom\b|\bm\.?\s*bed\b|\bmbr\b|\bgbr\b|\bcbr\b", text):
        return "bedroom"
    if re.search(r"\bkitchen\b", text):
        return "kitchen"
    if re.search(r"\bstudy\b|\boffice\b", text):
        return "study"
    if re.search(r"\bbath\b|\btoilet\b|\bwc\b", text):
        return "bathroom"
    return "default"


def floor_items_for_brief(brief: Dict[str, Any]) -> List[str]:
    """Required floor-plane items; user overrides via brief.moodboard_floor_items if set."""
    custom = brief.get("moodboard_floor_items")
    if isinstance(custom, list):
        items = [str(x).strip() for x in custom if isinstance(x, str) and str(x).strip()]
        if items:
            return items
    kind = infer_room_kind(brief)
    return list(ROOM_FLOOR_STANDARDS.get(kind, ROOM_FLOOR_STANDARDS["default"]))


def floor_items_block(brief: Dict[str, Any]) -> str:
    items = floor_items_for_brief(brief)
    room = str(brief.get("selected_room_name") or brief.get("space_type") or "room").strip()
    lines = [
        f"MANDATORY FLOOR FURNITURE for {room} (must appear on the floor plane in the photograph, not only wall decor):",
    ]
    for it in items:
        lines.append(f"  • {it}")
    lines.append(
        "Do not render an empty floor when the room type requires a table, bed, or seating group in the center."
    )
    return "\n".join(lines)


def enrich_moodboard_image_prompt(
    prompt: str,
    *,
    brief: Dict[str, Any],
    zone_id: str,
    zone_type: str,
    components: List[str],
) -> str:
    """Append floor-furniture rules so wall shots still show dining table, rug, etc."""
    floor_block = floor_items_block(brief)
    style = str(brief.get("style_direction") or "").strip()
    notes = str(brief.get("notes") or "").strip()
    comp_txt = ", ".join(components) if components else "as listed"

    if zone_id == "floor" or zone_type == "floor":
        extra = (
            f"{floor_block}\n\n"
            "SHOT: Wide angle or three-quarter view showing the FULL floor layout; "
            f"hero focus on center-floor furniture ({comp_txt}). Walls visible at edges. "
            "Photorealistic interior moodboard panel."
        )
    elif zone_id == "overview" or zone_type == "overview":
        extra = (
            f"{floor_block}\n\n"
            "SHOT: Full room vignette — all walls partially visible AND every mandatory floor item clearly shown."
        )
    else:
        extra = (
            f"{floor_block}\n\n"
            f"SHOT: This panel highlights the {zone_id.upper()} wall ({comp_txt}) but the camera must be "
            "wide enough that mandatory floor furniture remains visible in the foreground/center of the room. "
            "Never crop out the dining table / bed / coffee table if required for this room type."
        )

    if style:
        extra += f"\nStyle: {style}."
    if notes:
        extra += f"\nNotes: {notes[:200]}."

    base = (prompt or "").strip()
    if floor_block in base:
        return base
    return f"{base}\n\n{extra}".strip()


def ensure_floor_panel(
    panels: List[Dict[str, Any]],
    *,
    brief: Dict[str, Any],
    variants_per_wall: int,
) -> List[Dict[str, Any]]:
    """Inject a floor-layout panel if the planner omitted it (common for dining/living)."""
    kind = infer_room_kind(brief)
    if kind in ("bathroom",):
        return panels
    has_floor = any(
        isinstance(p, dict) and str(p.get("zone_id") or "").lower() in ("floor", "overview")
        for p in panels
    )
    if has_floor:
        return panels

    room = str(brief.get("selected_room_name") or brief.get("space_type") or "Room").strip()
    floor_items = floor_items_for_brief(brief)
    n = max(1, min(4, int(variants_per_wall)))
    variants: List[Dict[str, Any]] = []
    labels = ["Layout A", "Layout B", "Layout C", "Layout D"]
    for i in range(n):
        label = labels[i] if i < len(labels) else f"Option {i + 1}"
        comp_extra = ""
        if kind == "dining" and i == 1:
            comp_extra = " with bench seating on one side"
        elif kind == "dining" and i == 2:
            comp_extra = " round table variant"
        variants.append(
            {
                "label": label,
                "components": floor_items[:4],
                "image_prompt": (
                    f"Photorealistic moodboard: {room} — center floor layout. "
                    f"Show {', '.join(floor_items[:3])}{comp_extra}. "
                    "Wide interior shot, natural light, professional staging."
                ),
            }
        )

    floor_panel = {
        "zone_id": "floor",
        "zone_type": "floor",
        "title": f"{room} — floor layout",
        "openings_summary": "Center-floor furniture per room standards",
        "variants": variants,
    }
    return [floor_panel] + list(panels)


def moodboard_plan_schema() -> Dict[str, Any]:
    variant_schema = {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "components": {"type": "array", "items": {"type": "string"}},
            "image_prompt": {"type": "string"},
        },
        "required": ["label", "components", "image_prompt"],
    }
    panel_schema = {
        "type": "object",
        "properties": {
            "zone_id": {"type": "string"},
            "zone_type": {"type": "string"},
            "title": {"type": "string"},
            "openings_summary": {"type": "string"},
            "variants": {"type": "array", "items": variant_schema},
        },
        "required": ["zone_id", "zone_type", "title", "openings_summary", "variants"],
    }
    return {
        "type": "object",
        "properties": {
            "suggested_wall_assignments": {
                "type": "object",
                "properties": {
                    "north": {"type": "array", "items": {"type": "string"}},
                    "south": {"type": "array", "items": {"type": "string"}},
                    "east": {"type": "array", "items": {"type": "string"}},
                    "west": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["north", "south", "east", "west"],
            },
            "suggested_floor_items": {"type": "array", "items": {"type": "string"}},
            "panels": {"type": "array", "items": panel_schema},
        },
        "required": ["panels"],
    }


def merge_suggested_assignments(brief: Dict[str, Any], suggested: Any) -> Dict[str, Any]:
    """Fill empty wall_assignments from planner suggestions."""
    if not isinstance(suggested, dict):
        return brief
    current = normalize_wall_assignments(brief.get("wall_assignments"))
    has_any = any(current[k] for k in WALL_ZONE_IDS)
    if has_any:
        return brief
    out = dict(brief)
    out["wall_assignments"] = normalize_wall_assignments(suggested)
    return out


def merge_suggested_floor_items(brief: Dict[str, Any], suggested: Any) -> Dict[str, Any]:
    if isinstance(suggested, list) and suggested:
        items = [str(x).strip() for x in suggested if isinstance(x, str) and str(x).strip()]
        if items:
            out = dict(brief)
            out["moodboard_floor_items"] = items
            return out
    return brief
