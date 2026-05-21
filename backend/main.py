from __future__ import annotations

import base64
import logging
import os
import re
import traceback
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.llm import (
    active_provider,
    env_config,
    extract_rooms_from_floorplan,
    extract_room_dimensions_from_floorplan,
    extract_wall_openings_from_floorplan,
    generate_catalog_designs,
    generate_images,
    generate_moodboard_prompts,
    generate_next_questions,
)
from backend.catalog import load_catalog
from backend.http_errors import http_exception_from_llm_error
from backend.wall_placement import (
    enhance_image_prompt_for_compass,
    format_placement_verification,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("interior_copilot")
logger.info("Starting Interior Copilot API with LLM provider: %s", active_provider())

app = FastAPI(title="Interior Copilot API", version="0.1.0")

_DEFAULT_BRIEF: Dict[str, Any] = {
    "space_type": None,
    "style_direction": None,
    "mood_keywords": [],
    "color_preferences": [],
    "material_preferences": [],
    "budget_band": None,
    "must_include": [],
    "must_avoid": [],
    "notes": "",
    "room_length_m": None,
    "room_width_m": None,
    "ceiling_height_m": None,
    "use_floorplan_image_for_scale_only": False,
    "rooms_detected": [],
    "selected_room_id": None,
    "selected_room_name": None,
    "wall_assignments": {
        "north": [],
        "south": [],
        "east": [],
        "west": [],
    },
    "wall_openings": {
        "north": [],
        "south": [],
        "east": [],
        "west": [],
    },
    "floorplan_north_clockwise_deg": 0.0,
}


def _merge_brief(brief: Dict[str, Any]) -> Dict[str, Any]:
    return {**_DEFAULT_BRIEF, **(brief or {})}


def _num_or_none(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        x = float(v)
        return x if x > 0 else None
    if isinstance(v, str) and v.strip():
        try:
            x = float(v.strip())
            return x if x > 0 else None
        except ValueError:
            return None
    return None


def _dims_ok(brief: Dict[str, Any]) -> bool:
    ln = _num_or_none(brief.get("room_length_m"))
    wd = _num_or_none(brief.get("room_width_m"))
    return ln is not None and wd is not None


def _selected_room_ok(brief: Dict[str, Any], *, has_floorplan_image: bool = False) -> bool:
    """Room selection only matters when an actual floor plan image was uploaded and >1 rooms were detected."""
    if not has_floorplan_image:
        return True
    rooms = brief.get("rooms_detected") or []
    if not isinstance(rooms, list) or len(rooms) <= 1:
        return True
    rid = brief.get("selected_room_id")
    return isinstance(rid, str) and bool(rid.strip())


_EMPTY_WALL_OPENINGS: Dict[str, List[str]] = {"north": [], "south": [], "east": [], "west": []}


def _normalize_wall_openings(raw: Any) -> Dict[str, List[str]]:
    if not isinstance(raw, dict):
        return dict(_EMPTY_WALL_OPENINGS)
    out: Dict[str, List[str]] = {}
    for k in ("north", "south", "east", "west"):
        v = raw.get(k) or []
        if isinstance(v, list):
            out[k] = [str(x).strip() for x in v if isinstance(x, str) and str(x).strip()]
        else:
            out[k] = []
    return out


def _north_deg_from_brief(brief: Dict[str, Any]) -> float:
    v = brief.get("floorplan_north_clockwise_deg")
    try:
        return float(v) % 360.0
    except (TypeError, ValueError):
        return 0.0


def _room_target_for_openings(brief: Dict[str, Any]) -> tuple[str | None, str | None]:
    """Room id + name used to scope door/window extraction."""
    rooms = brief.get("rooms_detected") or []
    if not isinstance(rooms, list) or not rooms:
        return None, None
    if len(rooms) == 1:
        r0 = rooms[0]
        if not isinstance(r0, dict):
            return None, None
        rid = str(r0.get("id") or "").strip() or None
        rnm = str(r0.get("name") or "").strip() or None
        return rid, rnm
    sel = brief.get("selected_room_id")
    if not isinstance(sel, str) or not sel.strip():
        return None, None
    sid = sel.strip()
    for r in rooms:
        if isinstance(r, dict) and str(r.get("id")) == sid:
            rnm = str(r.get("name") or "").strip() or None
            return sid, rnm
    sn = brief.get("selected_room_name")
    if isinstance(sn, str) and sn.strip():
        return sid, sn.strip()
    return sid, None


_DIM_PATTERN = re.compile(
    r"(?P<a>\d+(?:\.\d+)?)\s*(?P<au>m|meter|metre|metres|meters|ft|feet|'|cm|mm)?\s*[x×*]\s*"
    r"(?P<b>\d+(?:\.\d+)?)\s*(?P<bu>m|meter|metre|metres|meters|ft|feet|'|cm|mm)?",
    re.IGNORECASE,
)


def _to_metres(value: float, unit: str | None) -> float | None:
    if value <= 0:
        return None
    u = (unit or "").lower().strip()
    if u in ("", "m", "meter", "metre", "metres", "meters"):
        return value
    if u in ("ft", "feet", "'"):
        return round(value * 0.3048, 3)
    if u == "cm":
        return round(value / 100.0, 3)
    if u == "mm":
        return round(value / 1000.0, 3)
    return value


_WALL_ITEM_LABELS: Dict[str, str] = {
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


def _format_wall_layout_text(brief: Dict[str, Any]) -> str:
    walls = brief.get("wall_assignments") or {}
    if not isinstance(walls, dict):
        return ""
    rows: List[str] = []
    label_for = lambda v: _WALL_ITEM_LABELS.get(str(v), str(v).replace("_", " "))
    for wall_id, wall_name in [("north", "NORTH"), ("south", "SOUTH"), ("east", "EAST"), ("west", "WEST")]:
        items = walls.get(wall_id) or []
        if isinstance(items, list) and items:
            pretty = ", ".join(label_for(x) for x in items if isinstance(x, str) and x.strip())
            if pretty:
                rows.append(f"- {wall_name} wall: {pretty}.")
    return "\n".join(rows)


def _format_wall_openings_text(brief: Dict[str, Any]) -> str:
    walls = brief.get("wall_openings") or {}
    if not isinstance(walls, dict):
        return ""
    rows: List[str] = []
    for wall_id, wall_name in [("north", "NORTH"), ("south", "SOUTH"), ("east", "EAST"), ("west", "WEST")]:
        items = walls.get(wall_id) or []
        if isinstance(items, list) and items:
            pretty = "; ".join(str(x).strip() for x in items if isinstance(x, str) and str(x).strip())
            if pretty:
                rows.append(f"- {wall_name}: {pretty}.")
    return "\n".join(rows)


def _has_opposing_walls(brief: Dict[str, Any]) -> bool:
    walls = brief.get("wall_assignments") or {}
    if not isinstance(walls, dict):
        return False
    ns = bool(walls.get("north")) and bool(walls.get("south"))
    ew = bool(walls.get("east")) and bool(walls.get("west"))
    return ns or ew


def _extract_dims_from_chat(chat_history: List[Dict[str, str]]) -> Dict[str, float] | None:
    """Best-effort: pull L×W from the user's chat turns. Returns metres."""
    for msg in reversed(chat_history or []):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        text = str(msg.get("content") or "")
        m = _DIM_PATTERN.search(text)
        if not m:
            continue
        try:
            a = float(m.group("a"))
            b = float(m.group("b"))
        except (TypeError, ValueError):
            continue
        au = m.group("au") or m.group("bu")
        bu = m.group("bu") or m.group("au")
        ln = _to_metres(a, au)
        wd = _to_metres(b, bu)
        if ln and wd and 1.5 <= ln <= 30 and 1.5 <= wd <= 30:
            return {"room_length_m": ln, "room_width_m": wd}
    return None


def _merge_extracted_floorplan_dims(brief: Dict[str, Any], extracted: Dict[str, Any]) -> Dict[str, Any]:
    """Fills L/W/H from a dedicated floor-plan vision read when the user has not already supplied both L and W."""
    out = dict(brief)
    if not isinstance(extracted, dict) or not extracted.get("readable_from_plan"):
        return out
    ln = _num_or_none(extracted.get("room_length_m"))
    wd = _num_or_none(extracted.get("room_width_m"))
    if ln and wd and not _dims_ok(out):
        out["room_length_m"] = ln
        out["room_width_m"] = wd
    ch = _num_or_none(extracted.get("ceiling_height_m"))
    if ch and _num_or_none(out.get("ceiling_height_m")) is None:
        out["ceiling_height_m"] = ch
    return out


def _filter_manual_dimension_questions(questions: List[str], *, has_floorplan_image: bool) -> List[str]:
    """Drop 'type your room size' style questions when a floor plan image was supplied (dimensions should come from the plan)."""
    if not has_floorplan_image:
        return [q for q in questions if isinstance(q, str)]
    markers = (
        "length and width",
        "length × width",
        "length x width",
        "room length",
        "width in metres",
        "width in meters",
        "ceiling height if known",
        "numeric size",
    )
    out: List[str] = []
    for q in questions:
        if not isinstance(q, str):
            continue
        low = q.lower()
        if any(m in low for m in markers):
            continue
        out.append(q)
    return out


def _gate_intake_result(
    updated_brief: Dict[str, Any],
    model_questions: List[str],
    max_questions: int,
    *,
    has_floorplan_image: bool = False,
) -> IntakeResponse:
    """
    Intake gate. Required to mark the brief complete:
      1) Floor plan image uploaded
      2) Room selected (when the plan has multiple rooms)
      3) Interior style direction
      4) Budget band (INR)
      5) Wardrobe / module style direction  (stashed into notes as "Wardrobe style: ...")
      6) Mood keywords (non-empty)
    Materials are auto-defaulted to "designer's choice" if not provided.
    We never pad with extra model-generated questions; the user only sees the
    strictly missing items, max 4 at a time.
    """
    b: Dict[str, Any] = dict(updated_brief)
    qs: List[str] = []
    max_q = max(1, min(8, max_questions))

    def push(msg: str) -> None:
        if msg and msg not in qs:
            qs.append(msg)

    mp = b.get("material_preferences")
    notes_str = str(b.get("notes") or "")
    notes_l = notes_str.lower()
    materials_present = isinstance(mp, list) and len(mp) > 0
    materials_designer_choice = any(
        x in notes_l for x in ("designer", "surprise", "any material", "no preference", "up to you")
    )
    if not materials_present and not materials_designer_choice:
        notes_str = (notes_str + ("\n" if notes_str else "") + "Materials: designer's choice.").strip()
        notes_l = notes_str.lower()
        b["notes"] = notes_str

    if not has_floorplan_image:
        push("Please upload a floor plan image so I can read the room layout and dimensions.")

    if has_floorplan_image:
        rooms = b.get("rooms_detected") or []
        if isinstance(rooms, list) and len(rooms) > 1 and not _selected_room_ok(b, has_floorplan_image=True):
            push("Your floor plan has multiple rooms. Which room should I design?")

    sd = b.get("style_direction")
    has_style = bool(sd and isinstance(sd, str) and sd.strip())
    if not has_style:
        push(
            "Which interior style should we follow (e.g. modern minimal, Indian contemporary, Japandi, industrial, Scandinavian)?"
        )

    bb = b.get("budget_band")
    has_budget = bool(bb and str(bb).strip())
    if not has_budget:
        push("What is your approximate budget band in INR (for example: under ₹3 lakh, ₹3–8 lakh, ₹8–15 lakh, ₹15 lakh+)?")

    has_wardrobe_style = "wardrobe style:" in notes_l
    if not has_wardrobe_style:
        push("What style direction do you prefer for the wardrobes? (e.g., modern, traditional, minimalist, rustic)")

    mk = b.get("mood_keywords")
    has_mood = isinstance(mk, list) and len([k for k in mk if isinstance(k, str) and k.strip()]) > 0
    if not has_mood:
        push("What mood or atmosphere do you want to create? (e.g., cozy, elegant, vibrant) Please provide keywords.")

    missing: List[str] = []
    if not has_floorplan_image:
        missing.append("floorplan_image")
    if not _selected_room_ok(b, has_floorplan_image=has_floorplan_image):
        missing.append("room_selection")
    if not has_style:
        missing.append("style")
    if not has_budget:
        missing.append("budget")
    if not has_wardrobe_style:
        missing.append("wardrobe_style")
    if not has_mood:
        missing.append("mood")

    is_complete = len(missing) == 0
    if is_complete:
        qs = []
    elif not qs:
        push("Please share what's missing so I can generate designs: " + ", ".join(missing) + ".")

    return IntakeResponse(is_complete=is_complete, updated_brief=b, questions=qs[:max_q])


def _assert_brief_ready_for_designs(brief: Dict[str, Any]) -> None:
    if not (_dims_ok(brief) or bool(brief.get("use_floorplan_image_for_scale_only"))):
        raise HTTPException(
            status_code=400,
            detail=(
                "Intake incomplete: add room length and width in metres (via chat), "
                "or confirm in chat that the layout should be scaled only from the floor plan image."
            ),
        )
    sd = brief.get("style_direction")
    if not sd or (isinstance(sd, str) and not sd.strip()):
        raise HTTPException(status_code=400, detail="Intake incomplete: add a style direction in chat.")
    bb = brief.get("budget_band")
    if not bb or (isinstance(bb, str) and not str(bb).strip()):
        raise HTTPException(status_code=400, detail="Intake incomplete: add a budget band in INR in chat.")

def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["*"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ImagePayload(BaseModel):
    mime_type: str
    data_base64: str


class IntakeRequest(BaseModel):
    brief: Dict[str, Any] = Field(default_factory=dict)
    chat_history: List[ChatMessage] = Field(default_factory=list)
    context_images: List[ImagePayload] = Field(default_factory=list)
    floorplan_images: List[ImagePayload] = Field(
        default_factory=list,
        description="Floor plan image(s) only. Used to read dimensions and to skip manual room-size gate questions.",
    )
    max_questions: int = 3


class IntakeResponse(BaseModel):
    is_complete: bool
    updated_brief: Dict[str, Any]
    questions: List[str]


class GenerateRequest(BaseModel):
    brief: Dict[str, Any]
    context_images: List[ImagePayload] = Field(default_factory=list)
    num_images: int = Field(default=3, ge=1, le=3)


class GenerateResponse(BaseModel):
    prompts: List[str]
    images_base64_png: List[str]

class DesignMaterialLine(BaseModel):
    material_id: str
    name: str
    unit: str
    unit_price: float
    quantity: float
    subtotal: float


class DesignItem(BaseModel):
    id: str
    name: str
    category: str
    price: float


class DesignVariant(BaseModel):
    title: str
    rationale: str
    placement_summary: str = ""
    catalog_items: List[DesignItem]
    materials: List[DesignMaterialLine]
    estimated_total: float
    image_base64_png: str | None = None
    prompt: str


class DesignsRequest(BaseModel):
    brief: Dict[str, Any] = Field(default_factory=dict)
    chat_history: List[ChatMessage] = Field(default_factory=list)
    floorplan_text: str | None = None
    floorplan_images: List[ImagePayload] = Field(default_factory=list)
    style_reference_images: List[ImagePayload] = Field(default_factory=list)
    num_designs: int = Field(default=3, ge=2, le=5)


class DesignsResponse(BaseModel):
    currency: str = "INR"
    designs: List[DesignVariant]


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "llm_provider": active_provider()}


@app.post("/api/intake", response_model=IntakeResponse)
def intake(req: IntakeRequest) -> IntakeResponse:
    try:
        cfg = env_config()
        merged_brief = _merge_brief(req.brief)
        floor_imgs = [img.model_dump() for img in req.floorplan_images]

        if floor_imgs:
            try:
                rooms = extract_rooms_from_floorplan(cfg=cfg, floorplan_images=floor_imgs)
                if isinstance(rooms, dict) and isinstance(rooms.get("rooms"), list):
                    merged_brief["rooms_detected"] = rooms.get("rooms") or []
            except Exception:
                pass

        if floor_imgs and not _dims_ok(merged_brief):
            try:
                extracted = extract_room_dimensions_from_floorplan(cfg=cfg, floorplan_images=floor_imgs)
                merged_brief = _merge_extracted_floorplan_dims(merged_brief, extracted)
            except Exception:
                pass

        merged_brief["floorplan_north_clockwise_deg"] = _north_deg_from_brief(merged_brief)
        rid_o, rnm_o = _room_target_for_openings(merged_brief)
        merged_brief["wall_openings"] = dict(_EMPTY_WALL_OPENINGS)
        if floor_imgs and (rnm_o or rid_o):
            try:
                raw_o = extract_wall_openings_from_floorplan(
                    cfg=cfg,
                    floorplan_images=floor_imgs,
                    target_room_id=rid_o,
                    target_room_name=rnm_o,
                    north_from_image_up_clockwise_deg=float(merged_brief["floorplan_north_clockwise_deg"]),
                )
                merged_brief["wall_openings"] = _normalize_wall_openings(
                    raw_o.get("wall_openings") if isinstance(raw_o, dict) else None
                )
            except Exception:
                logger.warning("extract_wall_openings_from_floorplan failed", exc_info=True)

        result = generate_next_questions(
            cfg=cfg,
            brief=merged_brief,
            chat_history=[m.model_dump() for m in req.chat_history],
            context_images=[img.model_dump() for img in req.context_images],
            max_questions=req.max_questions,
        )
        updated = dict(result.get("updated_brief") or merged_brief)
        if _dims_ok(merged_brief) and not _dims_ok(updated):
            updated["room_length_m"] = merged_brief.get("room_length_m")
            updated["room_width_m"] = merged_brief.get("room_width_m")
            if merged_brief.get("ceiling_height_m") is not None:
                updated["ceiling_height_m"] = merged_brief.get("ceiling_height_m")

        prev_walls = merged_brief.get("wall_assignments") or {}
        new_walls = updated.get("wall_assignments") or {}
        merged_walls = {
            "north": list(new_walls.get("north") or prev_walls.get("north") or []),
            "south": list(new_walls.get("south") or prev_walls.get("south") or []),
            "east": list(new_walls.get("east") or prev_walls.get("east") or []),
            "west": list(new_walls.get("west") or prev_walls.get("west") or []),
        }
        updated["wall_assignments"] = merged_walls

        updated["wall_openings"] = _normalize_wall_openings(merged_brief.get("wall_openings"))
        updated["floorplan_north_clockwise_deg"] = float(merged_brief.get("floorplan_north_clockwise_deg") or 0.0) % 360.0

        if not _dims_ok(updated):
            extracted = _extract_dims_from_chat([m.model_dump() for m in req.chat_history])
            if extracted:
                updated["room_length_m"] = extracted["room_length_m"]
                updated["room_width_m"] = extracted["room_width_m"]

        if not (updated.get("budget_band") and str(updated.get("budget_band")).strip()):
            for msg in reversed(req.chat_history):
                if msg.role != "user":
                    continue
                text = msg.content or ""
                low = text.lower()
                if any(kw in low for kw in ("lakh", "₹", "rs.", "rs ", "inr", "budget")):
                    updated["budget_band"] = text.strip()[:120]
                    break

        STYLE_HINTS = (
            "modern minimal",
            "modern",
            "minimal",
            "minimalist",
            "japandi",
            "scandinavian",
            "industrial",
            "indian contemporary",
            "contemporary",
            "traditional",
            "boho",
            "rustic",
            "art deco",
            "mid-century",
        )
        if not (updated.get("style_direction") and str(updated.get("style_direction")).strip()):
            for msg in reversed(req.chat_history):
                if msg.role != "user":
                    continue
                low = (msg.content or "").lower()
                for hint in STYLE_HINTS:
                    if hint in low:
                        updated["style_direction"] = hint
                        break
                if updated.get("style_direction"):
                    break

        existing_notes = str(updated.get("notes") or "")
        if "wardrobe style:" not in existing_notes.lower():
            wardrobe_style: str | None = None
            for msg in reversed(req.chat_history):
                if msg.role != "user":
                    continue
                low = (msg.content or "").lower()
                if "wardrobe" in low:
                    for hint in STYLE_HINTS:
                        if hint in low:
                            wardrobe_style = hint
                            break
                if not wardrobe_style:
                    for hint in STYLE_HINTS:
                        if hint in low:
                            wardrobe_style = hint
                            break
                if wardrobe_style:
                    break
            if wardrobe_style:
                updated["notes"] = (existing_notes + ("\n" if existing_notes else "") + f"Wardrobe style: {wardrobe_style}.").strip()

        mk = updated.get("mood_keywords")
        has_mood = isinstance(mk, list) and len([k for k in mk if isinstance(k, str) and k.strip()]) > 0
        if not has_mood:
            MOOD_HINTS = (
                "cozy",
                "warm",
                "calm",
                "serene",
                "elegant",
                "vibrant",
                "playful",
                "bold",
                "luxurious",
                "airy",
                "bright",
                "moody",
                "dramatic",
                "fresh",
                "minimal",
                "rustic",
                "natural",
                "earthy",
            )
            collected: List[str] = []
            for msg in reversed(req.chat_history):
                if msg.role != "user":
                    continue
                low = (msg.content or "").lower()
                if any(tag in low for tag in ("mood", "atmosphere", "feel", "vibe")) or len(collected) == 0:
                    for hint in MOOD_HINTS:
                        if hint in low and hint not in collected:
                            collected.append(hint)
                if collected:
                    break
            if collected:
                updated["mood_keywords"] = collected

        return _gate_intake_result(
            updated,
            list(result.get("questions") or []),
            req.max_questions,
            has_floorplan_image=bool(floor_imgs),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Intake failed:\n%s", traceback.format_exc())
        raise http_exception_from_llm_error(e) from e


@app.post("/api/moodboard", response_model=GenerateResponse)
def moodboard(req: GenerateRequest) -> GenerateResponse:
    try:
        cfg = env_config()
        prompts = generate_moodboard_prompts(
            cfg=cfg, brief=req.brief, n=req.num_images, context_images=[img.model_dump() for img in req.context_images]
        )
        images_b64: List[str] = []
        for p in prompts[: req.num_images]:
            imgs = generate_images(cfg=cfg, prompt=p, n=1)
            if imgs:
                images_b64.append(base64.b64encode(imgs[0]).decode("utf-8"))
        return GenerateResponse(prompts=prompts[: req.num_images], images_base64_png=images_b64)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Moodboard failed:\n%s", traceback.format_exc())
        raise http_exception_from_llm_error(e) from e


@app.post("/api/designs", response_model=DesignsResponse)
def designs(req: DesignsRequest) -> DesignsResponse:
    """
    Generates 2–3 design variants constrained to the local catalog.
    Accepts a floor plan in image and/or text form.
    """
    try:
        cfg = env_config()
        catalog = load_catalog()
        merged_brief = _merge_brief(req.brief)
        _assert_brief_ready_for_designs(merged_brief)

        chat_for_designs: List[Dict[str, str]] = [m.model_dump() for m in req.chat_history]
        wall_layout_text = _format_wall_layout_text(merged_brief)
        openings_text = _format_wall_openings_text(merged_brief)
        has_opposing = _has_opposing_walls(merged_brief)
        extra_msgs: List[str] = []
        if wall_layout_text:
            logger.info("Wall assignments received:\n%s", wall_layout_text)
            extra_msgs.append(
                "WALL LAYOUT (mandatory placement — items must visibly sit on the named walls):\n"
                + wall_layout_text
                + "\n\nCAMERA RULE: use a two-point/corner perspective from the "
                + ("south-west corner looking toward the north-east" if has_opposing else "diagonally opposite corner")
                + " so that the listed walls (especially any opposing N+S or E+W pair) are BOTH visible in the same frame. "
                "Do NOT shoot straight-on at one wall; the rendered image must show the wall placements above. "
                "Repeat the wall placement verbatim in the image_prompt and acknowledge it in the rationale."
            )
        if openings_text:
            logger.info("Wall openings from plan:\n%s", openings_text)
            extra_msgs.append(
                "DETECTED OPENINGS FROM FLOOR PLAN (doors / windows — keep in renders):\n"
                + openings_text
                + "\n\nPlace each listed opening on the correct compass wall; do not move doors or windows to a different wall. "
                "Mention key openings in the image_prompt when they affect furniture placement."
            )
        placement_map = format_placement_verification(merged_brief)
        if placement_map.strip():
            extra_msgs.append(
                "PLACEMENT VERIFICATION (user must be able to check N/S/E/W in your output):\n"
                + placement_map
                + "\n\nIn every image_prompt: include a small compass-rose graphic in a corner (no N/S/E/W letters on the image). "
                "Name each major item with its compass wall in the prompt text (e.g. 'queen bed centred on NORTH wall'). "
                "In every rationale: start with 'Layout:' then add 'Compass placement:' repeating the map above item-by-item."
            )
        if extra_msgs:
            chat_for_designs = chat_for_designs + [{"role": "user", "content": "\n\n".join(extra_msgs)}]

        planned = generate_catalog_designs(
            cfg=cfg,
            brief=merged_brief,
            chat_history=chat_for_designs,
            floorplan_text=req.floorplan_text,
            floorplan_images=[img.model_dump() for img in req.floorplan_images],
            style_reference_images=[img.model_dump() for img in req.style_reference_images],
            num_designs=req.num_designs,
        )

        # If the planner returns near-identical options (common failure mode),
        # re-run once with an explicit diversity constraint.
        try:
            ds = planned.get("designs") or []
            sets = []
            for d in ds:
                if isinstance(d, dict):
                    ids = d.get("catalog_item_ids") or []
                    if isinstance(ids, list):
                        sets.append(tuple(sorted(str(x) for x in ids if isinstance(x, str))))
            if len(set(sets)) <= 1 and len(sets) >= 2:
                stronger = list(chat_for_designs) + [
                    {
                        "role": "user",
                        "content": (
                            "The 2–3 design options MUST be meaningfully different. "
                            "Use different sofa SKUs across options, and vary rug/lighting. "
                            "Respect my budget_band, material_preferences, AND wall_assignments."
                        ),
                    }
                ]
                planned = generate_catalog_designs(
                    cfg=cfg,
                    brief=merged_brief,
                    chat_history=stronger,
                    floorplan_text=req.floorplan_text,
                    floorplan_images=[img.model_dump() for img in req.floorplan_images],
                    style_reference_images=[img.model_dump() for img in req.style_reference_images],
                    num_designs=req.num_designs,
                )
        except Exception:
            pass

        # If the user asked for a material (e.g. "stone") but the planned selections do not include it,
        # re-run once with an explicit constraint (only when catalog has such materials).
        try:
            prefs = merged_brief.get("material_preferences") or []
            prefs_l = [str(x).strip().lower() for x in prefs if isinstance(x, str)]
            wants_stone = any("stone" in p for p in prefs_l)
            if wants_stone:
                ds = planned.get("designs") or []
                has_stone = False
                for d in ds:
                    if not isinstance(d, dict):
                        continue
                    ids = d.get("catalog_item_ids") or []
                    if not isinstance(ids, list):
                        continue
                    for iid in ids:
                        it = catalog.items_by_id.get(str(iid))
                        if not it:
                            continue
                        if any(mid.startswith("mat_stone_") for mid in it.material_ids):
                            has_stone = True
                            break
                    if has_stone:
                        break
                if not has_stone:
                    stronger = list(chat_for_designs) + [
                        {
                            "role": "user",
                            "content": (
                                "Material constraint: the user selected STONE. "
                                "Include at least one major visible stone element using the catalog: "
                                "stone-top bedside table or stone accent wall cladding. "
                                "Keep 3 options different from each other and respect wall_assignments."
                            ),
                        }
                    ]
                    planned = generate_catalog_designs(
                        cfg=cfg,
                        brief=merged_brief,
                        chat_history=stronger,
                        floorplan_text=req.floorplan_text,
                        floorplan_images=[img.model_dump() for img in req.floorplan_images],
                        style_reference_images=[img.model_dump() for img in req.style_reference_images],
                        num_designs=req.num_designs,
                    )
        except Exception:
            pass

        out: List[DesignVariant] = []
        for d in (planned.get("designs") or [])[: req.num_designs]:
            item_ids = [x for x in (d.get("catalog_item_ids") or []) if isinstance(x, str)]
            items: List[DesignItem] = []
            items_total = 0.0
            for iid in item_ids:
                it = catalog.items_by_id.get(iid)
                if not it:
                    continue
                items.append(DesignItem(id=it.id, name=it.name, category=it.category, price=it.price))
                items_total += float(it.price)

            mats_in = d.get("materials") or []
            mats_out: List[DesignMaterialLine] = []
            mats_total = 0.0
            if isinstance(mats_in, list):
                for m in mats_in:
                    if not isinstance(m, dict):
                        continue
                    mid = str(m.get("material_id") or "")
                    name = str(m.get("name") or "")
                    unit = str(m.get("unit") or "")
                    unit_price = float(m.get("unit_price") or 0.0)
                    qty = float(m.get("quantity") or 0.0)
                    subtotal = float(unit_price * qty)
                    mats_total += subtotal
                    if mid:
                        mats_out.append(
                            DesignMaterialLine(
                                material_id=mid,
                                name=name,
                                unit=unit,
                                unit_price=unit_price,
                                quantity=qty,
                                subtotal=subtotal,
                            )
                        )

            prompt = str(d.get("image_prompt") or "")
            prompt = enhance_image_prompt_for_compass(prompt, merged_brief)
            rationale = str(d.get("rationale") or "")
            if placement_map and placement_map not in rationale:
                rationale = (rationale.rstrip() + "\n\n" + placement_map).strip()

            image_b64: str | None = None
            if prompt:
                imgs = generate_images(cfg=cfg, prompt=prompt, n=1)
                if imgs:
                    image_b64 = base64.b64encode(imgs[0]).decode("utf-8")

            out.append(
                DesignVariant(
                    title=str(d.get("title") or "Design option"),
                    rationale=rationale,
                    placement_summary=placement_map,
                    catalog_items=items,
                    materials=mats_out,
                    estimated_total=float(items_total + mats_total),
                    image_base64_png=image_b64,
                    prompt=prompt,
                )
            )

        return DesignsResponse(currency=catalog.currency, designs=out)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Designs failed:\n%s", traceback.format_exc())
        raise http_exception_from_llm_error(e) from e

