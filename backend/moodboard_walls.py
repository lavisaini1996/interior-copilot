"""Wall-by-wall moodboard planning helpers (Mr Dileep–style panels per wall/zone)."""

from __future__ import annotations

import base64
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Tuple

from backend.wall_placement import (
    build_component_wall_shot_block,
    build_hero_wall_backdrop_block,
    build_layout_ascii_diagram,
    build_openings_detailed_block,
)

logger = logging.getLogger("interior_copilot.moodboard_walls")

WALL_ZONE_IDS = ("north", "south", "east", "west")
EXTRA_ZONE_IDS = ("ceiling", "overview", "floor")

COMPONENT_LABELS: Dict[str, str] = {
    "sofa": "Sofa",
    "sectional": "Sectional sofa",
    "accent_chair": "Accent chair",
    "ottoman": "Ottoman",
    "coffee_table": "Coffee table",
    "side_table": "Side table",
    "tv_unit": "TV unit",
    "console": "Console",
    "bookshelf": "Bookshelf",
    "sideboard": "Sideboard",
    "bar_cabinet": "Bar cabinet",
    "floor_lamp": "Floor lamp",
    "art": "Art / wall decor",
    "mirror": "Mirror",
    "planter": "Planter",
    "accent_wall": "Accent wall / paneling",
    "fireplace": "Fireplace",
    "bed": "Bed",
    "headboard": "Upholstered headboard",
    "wardrobe": "Wardrobe",
    "loft": "Loft storage",
    "bedside": "Bedside table",
    "dresser": "Dresser",
    "chest_of_drawers": "Chest of drawers",
    "study": "Study desk",
    "desk": "Desk",
    "reading_chair": "Reading chair",
    "bench": "Bench",
    "wall_sconces": "Wall sconces",
    "wallpaper": "Wallpaper feature",
    "dining_table": "Dining table",
    "dining_chairs": "Dining chairs",
    "crockery": "Crockery unit",
    "wine_rack": "Wine rack",
    "pendant_light": "Pendant light",
    "rug": "Area rug",
    "base_cabinets": "Base cabinets",
    "wall_cabinets": "Wall cabinets",
    "backsplash": "Backsplash",
    "vanity": "Vanity",
    "pooja_unit": "Pooja unit",
}

FREESTANDING_ITEMS = frozenset(
    {
        "sofa",
        "sectional",
        "accent_chair",
        "ottoman",
        "coffee_table",
        "side_table",
        "dining_table",
        "dining_chairs",
        "bench",
        "bed",
        "bedside",
        "dresser",
        "chest_of_drawers",
        "reading_chair",
        "desk",
        "study",
        "chair",
        "floor_lamp",
        "console",
        "seating",
        "cafe_table",
        "rug",
        "ottoman",
    }
)

WALL_BUILTIN_ITEMS = frozenset(
    {
        "tv_unit",
        "wardrobe",
        "loft",
        "headboard",
        "bookshelf",
        "sideboard",
        "bar_cabinet",
        "crockery",
        "wine_rack",
        "accent_wall",
        "wallpaper",
        "wall_sconces",
        "art",
        "mirror",
        "fireplace",
        "base_cabinets",
        "wall_cabinets",
        "backsplash",
        "vanity",
        "pooja_unit",
        "pendant_light",
        "wall_paneling",
        "jali",
        "lighting",
    }
)

ROOM_FLOOR_COMPONENT_IDS: Dict[str, List[str]] = {
    "dining": ["dining_table", "dining_chairs", "rug"],
    "living": ["coffee_table", "rug", "side_table"],
    "bedroom": ["bed", "bedside", "rug"],
    "kitchen": ["counter", "peninsula"],
    "study": ["desk", "chair", "rug"],
    "default": ["rug"],
}

COMPONENT_ALIASES: Dict[str, str] = {
    "sectional_sofa": "sectional",
    "tv": "tv_unit",
    "tv_unit": "tv_unit",
    "coffee_table": "coffee_table",
    "area_rug": "rug",
    "side_table": "side_table",
    "dining_chair": "dining_chairs",
    "accent_wall_paneling": "accent_wall",
}

VARIANT_LABELS = ("Option A", "Option B", "Option C", "Option D")

COMPONENT_VARIANT_HINTS: Dict[str, List[str]] = {
    "sofa": [
        "classic three-seater with tailored upholstery and slim wooden legs",
        "channel-tufted velvet with brass-capped feet and structured arms",
        "low-profile contemporary silhouette with linen fabric",
        "curved organic form with rich jewel-tone upholstery",
    ],
    "sectional": [
        "L-shaped sectional with chaise on the left",
        "U-shaped modular sectional with deep seats",
        "compact two-piece sectional for smaller rooms",
        "sectional with integrated storage ottoman module",
    ],
    "tv_unit": [
        "white marble slab center with fluted cream panels and brass vertical sconces",
        "dark green wainscot panels with tambour slats and warm LED strip accents",
        "minimal light-oak slat wall with floating black console shelf",
        "textured stone feature panel with integrated ambient cove lighting",
    ],
    "coffee_table": [
        "round white marble top with brushed brass base",
        "rectangular smoked-glass top with black metal frame",
        "nested set of two round wood tables",
        "sculptural stone pedestal coffee table",
    ],
    "rug": [
        "bold geometric pattern in gold and charcoal",
        "subtle neutral hand-knotted wool rug",
        "Moroccan-inspired trellis pattern",
        "solid plush rug in a deep accent color",
    ],
    "bed": [
        "upholstered platform bed with tall headboard",
        "low platform bed with wood frame and linen bedding",
        "wingback upholstered bed with nailhead trim",
        "minimal Japanese-inspired low bed with natural wood",
    ],
    "dining_table": [
        "rectangular solid-wood table for six to eight seats",
        "round marble-top dining table with pedestal base",
        "extendable dining table with tapered legs",
        "live-edge wood slab dining table with metal legs",
    ],
    "wardrobe": [
        "floor-to-ceiling flush sliding doors in matte lacquer",
        "fluted wood sliding wardrobe with bronze pulls",
        "glass-front wardrobe sections with internal lighting",
        "two-tone wardrobe with open display niche",
    ],
}

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


def normalize_component_id(raw: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", str(raw or "").strip().lower()).strip("_")
    return COMPONENT_ALIASES.get(s, s)


def component_display_label(component_id: str) -> str:
    cid = normalize_component_id(component_id)
    if cid in COMPONENT_LABELS:
        return COMPONENT_LABELS[cid]
    return cid.replace("_", " ").title()


def component_shot_type(component_id: str) -> str:
    cid = normalize_component_id(component_id)
    if cid in FREESTANDING_ITEMS:
        return "freestanding"
    if cid in WALL_BUILTIN_ITEMS:
        return "wall_builtin"
    return "freestanding" if cid in {"planter", "swing"} else "wall_builtin"


def _openings_for_wall(brief: Dict[str, Any], wall: str) -> str:
    openings = normalize_wall_openings(brief.get("wall_openings"))
    ops = openings.get(wall) or []
    return ", ".join(ops) if ops else ""


def _brief_materials_txt(brief: Dict[str, Any]) -> str:
    mats = brief.get("material_preferences")
    if isinstance(mats, list) and mats:
        return ", ".join(str(m).strip() for m in mats if str(m).strip())[:120]
    return ""


def _wall_backdrop_labels(brief: Dict[str, Any], wall: str, exclude_cid: str) -> List[str]:
    """Other items on the same wall that may appear in the zone background."""
    assignments = normalize_wall_assignments(brief.get("wall_assignments"))
    labels: List[str] = []
    exclude = normalize_component_id(exclude_cid)
    for item in assignments.get(wall) or []:
        iid = normalize_component_id(item)
        if iid and iid != exclude and component_display_label(iid) not in labels:
            labels.append(component_display_label(iid))
    return labels


def zone_background_block(brief: Dict[str, Any], wall: str, component_id: str) -> str:
    """Describe the styled zone backdrop that must appear with the hero component."""
    cid = normalize_component_id(component_id)
    label = component_display_label(cid)
    room = str(brief.get("selected_room_name") or brief.get("space_type") or "room").strip()
    style = str(brief.get("style_direction") or "").strip()
    materials = _brief_materials_txt(brief)
    colors = brief.get("color_preferences")
    color_txt = ""
    if isinstance(colors, list) and colors:
        color_txt = ", ".join(str(c).strip() for c in colors if str(c).strip())[:80]

    lines = [
        f"ZONE BACKGROUND — render the {label} inside its designed interior setting (not a plain studio backdrop):",
    ]

    if wall in WALL_ZONE_IDS:
        backdrops = _wall_backdrop_labels(brief, wall, cid)
        backdrop_block = build_hero_wall_backdrop_block(wall, cid, brief)
        if backdrop_block:
            lines.append(backdrop_block)
        else:
            openings = _openings_for_wall(brief, wall)
            lines.append(
                f"  • {wall.title()} wall behind the hero: full wall finish — paneling, moulding, paint, "
                "wallpaper, stone, or feature treatment matching the style brief."
            )
            if openings:
                lines.append(f"  • Openings on this wall only: {openings}.")
        if backdrops:
            lines.append(
                f"  • Same-wall context (supporting elements, not separate heroes): {', '.join(backdrops)}."
            )
        lines.append(
            "  • Visible floor finish in the lower third (marble, herringbone wood, tile, or rug edge at base)."
        )
        lines.append("  • Ceiling edge, cove, or architectural lighting at the top of frame when appropriate.")
    else:
        lines.append(
            f"  • {room} floor zone: show the room floor finish, baseboard, and soft wall glimpses at frame edges."
        )
        lines.append("  • Natural or architectural lighting consistent with the room style.")

    if materials:
        lines.append(f"  • Materials palette: {materials}.")
    if color_txt:
        lines.append(f"  • Color palette: {color_txt}.")
    if style:
        lines.append(f"  • Style direction: {style}.")

    lines.append(
        "The background must read as a real designed interior zone — not a grey sweep, white void, or catalog cutout."
    )
    lines.append(
        f"Hero = {label} only. Do NOT add furniture from other walls/zones or a full-room wide shot."
    )
    return "\n".join(lines)


def _floor_component_ids(brief: Dict[str, Any]) -> List[str]:
    custom = brief.get("moodboard_floor_items")
    if isinstance(custom, list) and custom:
        ids: List[str] = []
        for raw in custom:
            if not isinstance(raw, str) or not raw.strip():
                continue
            cid = normalize_component_id(raw)
            if cid and cid not in ids:
                ids.append(cid)
        if ids:
            return ids
    kind = infer_room_kind(brief)
    return list(ROOM_FLOOR_COMPONENT_IDS.get(kind, ROOM_FLOOR_COMPONENT_IDS["default"]))


def _generic_variant_hints(component_id: str, n: int) -> List[str]:
    label = component_display_label(component_id)
    base = [
        f"{label} — refined classic proportions and neutral palette",
        f"{label} — richer material mix with warm metal accents",
        f"{label} — contemporary minimal form with contrast textures",
        f"{label} — bold statement finish aligned with the style brief",
    ]
    return base[: max(1, n)]


COMPONENT_ONLY_MANDATE = (
    "=== COMPONENT-ONLY IMAGE (mandatory) ===\n"
    "Render exactly ONE catalog component in frame — tight crop on that item and its immediate wall zone.\n"
    "FORBIDDEN: full-room wide shot, panorama, opposing walls both visible, extra sofas/TVs/tables/beds, "
    "furnished living-room scene, overview layout.\n"
    "ALLOWED: hero component + its assigned wall materials + narrow floor strip + doors/windows on THAT wall only."
)


def build_compact_wall_structure_block(brief: Dict[str, Any], hero_wall: str) -> str:
    """Wall structure + placements from floor plan — compact, no full-room camera."""
    assignments = normalize_wall_assignments(brief.get("wall_assignments"))
    openings = normalize_wall_openings(brief.get("wall_openings"))
    room = str(brief.get("selected_room_name") or brief.get("space_type") or "room").strip()
    hero = str(hero_wall or "").strip().lower()

    lines: List[str] = [
        "FLOOR PLAN WALL STRUCTURE (binding — match attached plan; do not move items or openings):",
        f"Room: {room}.",
    ]

    ln = brief.get("room_length_m")
    wd = brief.get("room_width_m")
    try:
        if ln and wd and float(ln) > 0 and float(wd) > 0:
            lines.append(f"Proportions: {float(ln):.2f} m × {float(wd):.2f} m (north–south × east–west).")
    except (TypeError, ValueError):
        pass

    north_deg = brief.get("floorplan_north_clockwise_deg")
    if north_deg is not None:
        try:
            lines.append(
                f"Plan north: {float(north_deg) % 360:.0f}° clockwise from top of sheet — "
                "N/E/S/W walls follow the floor plan."
            )
        except (TypeError, ValueError):
            pass

    for wid, wname in [("north", "NORTH"), ("south", "SOUTH"), ("east", "EAST"), ("west", "WEST")]:
        items = [component_display_label(normalize_component_id(x)) for x in (assignments.get(wid) or [])]
        ops = [str(x).strip() for x in (openings.get(wid) or []) if str(x).strip()]
        furn = ", ".join(items) if items else "(none)"
        op_txt = "; ".join(ops) if ops else "(none)"
        tag = "  << HERO WALL FOR THIS IMAGE" if wid == hero else ""
        lines.append(f"  {wname}: furniture={furn}; openings={op_txt}.{tag}")

    lines.append(
        "Rules: furniture stays on its listed wall; openings only on listed walls; "
        "never invent or relocate doors/windows; never mirror the plan."
    )
    return "\n".join(lines)


def polish_component_moodboard_prompt(prompt: str, brief: Dict[str, Any]) -> str:
    """Light polish for single-component shots — avoids full-room render instructions."""
    out = (prompt or "").strip()
    note = (
        "Photorealistic single-component moodboard panel. Accurate scale. "
        "Match floor plan wall structure. No N/S/E/W text, logo, or watermark in the image."
    )
    if note.lower() not in out.lower():
        out = f"{out}\n\n{note}".strip()
    return out


def variant_hints_for_component(component_id: str, n: int) -> List[str]:
    cid = normalize_component_id(component_id)
    n = max(1, min(4, n))
    hints = COMPONENT_VARIANT_HINTS.get(cid) or _generic_variant_hints(cid, n)
    if len(hints) >= n:
        return hints[:n]
    out = list(hints)
    while len(out) < n:
        out.append(hints[-1])
    return out


def build_component_image_prompt(
    component_id: str,
    *,
    wall: str,
    brief: Dict[str, Any],
    variant_hint: str | None = None,
) -> str:
    """Deterministic base prompt for a single component image."""
    cid = normalize_component_id(component_id)
    label = component_display_label(cid)
    room = str(brief.get("selected_room_name") or brief.get("space_type") or "room").strip()
    style = str(brief.get("style_direction") or "").strip()
    shot = component_shot_type(cid)
    wall_txt = wall.title() if wall in WALL_ZONE_IDS else "center floor"
    variant_txt = (variant_hint or "").strip()

    bg = zone_background_block(brief, wall, cid)

    if shot == "freestanding":
        body = (
            f"Photorealistic interior moodboard: {room} — {label} as hero on the {wall_txt}, "
            f"shown WITH its styled zone background (wall treatment, floor finish, lighting).\n"
            f"{bg}\n"
            f"Three-quarter view: ONE {label} in front of the finished wall/floor setting. "
            f"No extra furniture from other zones, no full-room panorama."
        )
    else:
        body = (
            f"Photorealistic interior moodboard: {room} — {label} on {wall_txt} "
            f"with full wall-and-floor background context.\n"
            f"{bg}\n"
            f"Component-focused elevation: {label} integrated into the finished wall "
            f"(materials, joinery, lighting). No sofas, beds, or center-floor furniture from other zones."
        )
    if variant_txt:
        body += f" This option: {variant_txt}."
    return body


def build_component_variants(
    component_id: str,
    *,
    wall: str,
    brief: Dict[str, Any],
    n: int,
) -> List[Dict[str, Any]]:
    """Build n visually distinct style alternatives for the same component."""
    cid = normalize_component_id(component_id)
    count = max(1, min(4, int(n)))
    hints = variant_hints_for_component(cid, count)
    variants: List[Dict[str, Any]] = []
    for i in range(count):
        label = VARIANT_LABELS[i] if i < len(VARIANT_LABELS) else f"Option {i + 1}"
        variants.append(
            {
                "label": label,
                "components": [cid],
                "image_prompt": build_component_image_prompt(
                    cid,
                    wall=wall,
                    brief=brief,
                    variant_hint=hints[i],
                ),
            }
        )
    return variants


def _component_panel(
    component_id: str,
    *,
    wall: str,
    brief: Dict[str, Any],
    variants_per_component: int,
    title: str,
    openings_summary: str = "",
) -> Dict[str, Any]:
    return {
        "zone_id": wall,
        "zone_type": "component",
        "title": title,
        "openings_summary": openings_summary,
        "variants": build_component_variants(
            component_id,
            wall=wall,
            brief=brief,
            n=variants_per_component,
        ),
    }


def expand_panels_per_component(
    panels: List[Dict[str, Any]],
    *,
    brief: Dict[str, Any],
    variants_per_component: int = 3,
) -> List[Dict[str, Any]]:
    """One panel per component with multiple style variants each."""
    assignments = normalize_wall_assignments(brief.get("wall_assignments"))
    seen: set[tuple[str, str]] = set()
    out: List[Dict[str, Any]] = []

    for wall in WALL_ZONE_IDS:
        for comp in assignments[wall]:
            cid = normalize_component_id(comp)
            if not cid:
                continue
            key = (wall, cid)
            if key in seen:
                continue
            seen.add(key)
            label = component_display_label(cid)
            out.append(
                _component_panel(
                    cid,
                    wall=wall,
                    brief=brief,
                    variants_per_component=variants_per_component,
                    title=f"{label} — {wall.title()} wall",
                    openings_summary=_openings_for_wall(brief, wall),
                )
            )

    # Floor components only when user explicitly lists them (not auto coffee table/rug).
    custom_floor = brief.get("moodboard_floor_items")
    if isinstance(custom_floor, list):
        for raw in custom_floor:
            if not isinstance(raw, str) or not raw.strip():
                continue
            cid = normalize_component_id(raw)
            if not cid:
                continue
            key = ("floor", cid)
            if key in seen or any(normalize_component_id(c) == cid for w in WALL_ZONE_IDS for c in assignments[w]):
                continue
            seen.add(key)
            label = component_display_label(cid)
            out.append(
                _component_panel(
                    cid,
                    wall="floor",
                    brief=brief,
                    variants_per_component=variants_per_component,
                    title=f"{label} — floor",
                    openings_summary="User-specified floor component",
                )
            )

    if out:
        return out

    split: List[Dict[str, Any]] = []
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        zone_id = str(panel.get("zone_id") or "").strip().lower() or "wall"
        zone_type = str(panel.get("zone_type") or "wall").strip()
        title_base = str(panel.get("title") or zone_id).strip()
        openings_summary = str(panel.get("openings_summary") or "").strip()
        raw_vars = panel.get("variants")
        if not isinstance(raw_vars, list):
            continue
        for rv in raw_vars:
            if not isinstance(rv, dict):
                continue
            comps_raw = rv.get("components")
            comps = (
                [normalize_component_id(c) for c in comps_raw if isinstance(c, str) and str(c).strip()]
                if isinstance(comps_raw, list)
                else []
            )
            if not comps:
                guess = normalize_component_id(str(rv.get("label") or ""))
                comps = [guess] if guess else []
            prompt_base = str(rv.get("image_prompt") or "").strip()
            for cid in comps:
                if not cid:
                    continue
                key = (zone_id, cid)
                if key in seen:
                    continue
                seen.add(key)
                label = component_display_label(cid)
                variants = build_component_variants(
                    cid,
                    wall=zone_id,
                    brief=brief,
                    n=variants_per_component,
                )
                if prompt_base and variants:
                    variants[0]["image_prompt"] = prompt_base
                split.append(
                    {
                        "zone_id": zone_id,
                        "zone_type": "component",
                        "title": f"{label} — {title_base}",
                        "openings_summary": openings_summary,
                        "variants": variants,
                    }
                )
    return split or panels


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
    """Append shot-type rules: one component per image (freestanding vignette or wall elevation)."""
    floor_block = floor_items_block(brief)
    style = str(brief.get("style_direction") or "").strip()
    notes = str(brief.get("notes") or "").strip()
    primary = normalize_component_id(components[0]) if components else ""
    label = component_display_label(primary) if primary else "component"
    shot = component_shot_type(primary) if primary else "wall_builtin"

    if zone_type == "overview" or zone_id == "overview":
        extra = (
            f"{floor_block}\n\n"
            "SHOT: Full room vignette — all walls partially visible AND every mandatory floor item clearly shown."
        )
    elif shot == "freestanding" or (zone_id == "floor" and zone_type == "component"):
        bg = zone_background_block(brief, zone_id, primary)
        extra = (
            f"{COMPONENT_ONLY_MANDATE}\n\n"
            f"SHOT: Single {label} only — product vignette on the {zone_id.upper() if zone_id in WALL_ZONE_IDS else 'floor'} zone.\n"
            f"CAMERA: Medium-tight crop on this one {label}; wall/floor context at edges only.\n"
            f"{bg}\n"
            "Do not show other hero furniture. No full-room shot."
        )
    elif zone_id == "floor" or zone_type == "floor":
        bg = zone_background_block(brief, zone_id, primary)
        extra = (
            f"{COMPONENT_ONLY_MANDATE}\n\n"
            f"SHOT: Single floor component — {label} only.\n"
            f"{bg}\n"
            "Partial wall glimpses at edges OK; no other furniture heroes."
        )
    else:
        bg = zone_background_block(brief, zone_id, primary)
        extra = (
            f"{COMPONENT_ONLY_MANDATE}\n\n"
            f"SHOT: Wall component elevation — {label} on {zone_id.upper()} wall only.\n"
            "CAMERA: Straight-on or slight angle on this wall segment; tight crop.\n"
            f"{bg}\n"
            "TV-wall / feature-wall style vignette. No sofas, beds, or center-floor furniture."
        )

    if style:
        extra += f"\nStyle: {style}."
    if notes:
        extra += f"\nNotes: {notes[:200]}."

    extra += (
        "\nOUTPUT: Plain full-bleed photorealistic interior photograph only — "
        "no borders, titles, logos, material swatches, sidebar, or overlay text "
        "(Material Board framing is added after generation)."
    )

    base = (prompt or "").strip()
    if floor_block in base:
        return base
    return f"{base}\n\n{extra}".strip()


def finalize_moodboard_component_prompt(
    prompt: str,
    *,
    brief: Dict[str, Any],
    zone_id: str,
    zone_type: str,
    components: List[str],
) -> str:
    """Component-only prompt with floor-plan wall structure and correct wall placement."""
    primary = normalize_component_id(components[0]) if components else ""
    hero_wall = zone_id if zone_id in WALL_ZONE_IDS else "floor"
    style_prompt = enrich_moodboard_image_prompt(
        prompt,
        brief=brief,
        zone_id=zone_id,
        zone_type=zone_type,
        components=components,
    )

    blocks: List[str] = [COMPONENT_ONLY_MANDATE]

    if primary and hero_wall in WALL_ZONE_IDS:
        backdrop = build_hero_wall_backdrop_block(hero_wall, primary, brief)
        if backdrop:
            blocks.append(backdrop)

    structure = build_compact_wall_structure_block(brief, hero_wall)
    if structure:
        blocks.append(structure)

    openings_detail = build_openings_detailed_block(brief)
    if openings_detail:
        blocks.append(openings_detail)

    ascii_diag = build_layout_ascii_diagram(brief)
    if ascii_diag:
        blocks.append(ascii_diag)

    if primary:
        placement_shot = build_component_wall_shot_block(hero_wall, primary, brief)
        if placement_shot:
            blocks.append(placement_shot)

    blocks.append(style_prompt)
    combined = "\n\n".join(b for b in blocks if b.strip())
    return polish_component_moodboard_prompt(combined, brief)


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
        return ensure_default_wall_assignments(brief)
    current = normalize_wall_assignments(brief.get("wall_assignments"))
    has_any = any(current[k] for k in WALL_ZONE_IDS)
    if has_any:
        return brief
    out = dict(brief)
    out["wall_assignments"] = normalize_wall_assignments(suggested)
    return ensure_default_wall_assignments(out)


DEFAULT_WALL_ASSIGNMENTS_BY_ROOM: Dict[str, Dict[str, List[str]]] = {
    "living": {"north": ["tv_unit"], "south": ["sofa"], "east": [], "west": []},
    "bedroom": {"north": ["bed"], "west": ["tv_unit"], "south": [], "east": []},
    "dining": {"north": ["sideboard"], "south": [], "east": [], "west": []},
    "kitchen": {"north": ["wall_cabinets"], "south": ["base_cabinets"], "east": [], "west": []},
    "study": {"north": ["bookshelf"], "south": ["desk"], "east": [], "west": []},
    "bathroom": {"north": ["vanity"], "south": [], "east": [], "west": []},
}


def ensure_default_wall_assignments(brief: Dict[str, Any]) -> Dict[str, Any]:
    """Sensible default placements when the user has not clicked walls yet."""
    current = normalize_wall_assignments(brief.get("wall_assignments"))
    if any(current[k] for k in WALL_ZONE_IDS):
        return brief
    kind = infer_room_kind(brief)
    defaults = DEFAULT_WALL_ASSIGNMENTS_BY_ROOM.get(kind)
    if not defaults:
        return brief
    out = dict(brief)
    out["wall_assignments"] = normalize_wall_assignments(defaults)
    return out


def merge_suggested_floor_items(brief: Dict[str, Any], suggested: Any) -> Dict[str, Any]:
    if isinstance(suggested, list) and suggested:
        items = [str(x).strip() for x in suggested if isinstance(x, str) and str(x).strip()]
        if items:
            out = dict(brief)
            out["moodboard_floor_items"] = items
            return out
    return brief


MoodboardImageJob = Tuple[int, int, str]


def prioritize_moodboard_image_jobs(jobs: List[MoodboardImageJob]) -> List[MoodboardImageJob]:
    """Round-robin across panels so each wall gets at least one image when capped."""
    by_panel: Dict[int, List[MoodboardImageJob]] = {}
    for job in jobs:
        panel_idx = job[0]
        by_panel.setdefault(panel_idx, []).append(job)
    if not by_panel:
        return []
    ordered: List[MoodboardImageJob] = []
    max_rounds = max(len(v) for v in by_panel.values())
    for round_i in range(max_rounds):
        for panel_idx in sorted(by_panel):
            panel_jobs = by_panel[panel_idx]
            if round_i < len(panel_jobs):
                ordered.append(panel_jobs[round_i])
    return ordered


def render_moodboard_images_parallel(
    *,
    generate_one: Callable[[str], bytes | None],
    jobs: List[MoodboardImageJob],
    max_images: int,
    workers: int,
) -> Dict[Tuple[int, int], str]:
    """
    Run moodboard variant image generation concurrently.
    Returns map (panel_idx, variant_idx) -> base64 PNG.
    """
    if max_images <= 0 or not jobs:
        return {}

    selected = prioritize_moodboard_image_jobs(jobs)[:max_images]
    out: Dict[Tuple[int, int], str] = {}
    pool_workers = max(1, min(workers, len(selected)))

    def _run(job: MoodboardImageJob) -> Tuple[Tuple[int, int], str | None]:
        panel_idx, variant_idx, prompt = job
        try:
            raw = generate_one(prompt)
            if raw:
                return (panel_idx, variant_idx), base64.b64encode(raw).decode("utf-8")
        except Exception:
            logger.warning(
                "Moodboard wall image failed for panel %s variant %s",
                panel_idx,
                variant_idx,
                exc_info=True,
            )
        return (panel_idx, variant_idx), None

    with ThreadPoolExecutor(max_workers=pool_workers) as pool:
        futures = [pool.submit(_run, job) for job in selected]
        for fut in as_completed(futures):
            key, b64 = fut.result()
            if b64:
                out[key] = b64
    return out
