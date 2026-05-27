from __future__ import annotations

import base64
import logging
import os
import random
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
    extract_plan_north_from_floorplan,
    extract_wall_openings_from_floorplan,
    generate_catalog_designs,
    generate_images,
    generate_moodboard_prompts,
)
from backend.catalog import load_catalog
from backend.http_errors import http_exception_from_llm_error
from backend.wall_placement import (
    build_mandatory_layout_block,
    enhance_image_prompt_for_compass,
    enforce_wall_placement_in_prompt,
    format_placement_verification,
    normalize_dims_to_metres,
    WALL_ITEM_LABELS,
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


def _merge_plan_north(brief: Dict[str, Any], extracted: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(extracted, dict):
        return brief
    try:
        deg = float(extracted.get("north_clockwise_deg")) % 360.0
    except (TypeError, ValueError):
        return brief
    out = dict(brief)
    out["floorplan_north_clockwise_deg"] = deg
    if extracted.get("has_north_indicator") is not None:
        out["floorplan_north_has_indicator"] = bool(extracted.get("has_north_indicator"))
    notes = extracted.get("notes")
    if isinstance(notes, str) and notes.strip():
        out["floorplan_north_notes"] = notes.strip()
    return out


def _reconcile_selected_room(brief: Dict[str, Any]) -> Dict[str, Any]:
    """Keep selected_room_id in sync with rooms_detected (match by id, then by name)."""
    rooms = brief.get("rooms_detected") or []
    if not isinstance(rooms, list) or not rooms:
        return brief
    sel_id = brief.get("selected_room_id")
    sel_name = brief.get("selected_room_name")
    if not sel_id and not sel_name:
        return brief
    if isinstance(sel_id, str) and sel_id.strip():
        sid = sel_id.strip()
        for r in rooms:
            if isinstance(r, dict) and str(r.get("id") or "").strip() == sid:
                out = dict(brief)
                out["selected_room_id"] = sid
                if not sel_name and r.get("name"):
                    out["selected_room_name"] = str(r.get("name"))
                return out
    if isinstance(sel_name, str) and sel_name.strip():
        target = sel_name.strip().lower()
        for r in rooms:
            if not isinstance(r, dict):
                continue
            rname = str(r.get("name") or "").strip()
            if rname.lower() == target:
                out = dict(brief)
                out["selected_room_id"] = str(r.get("id") or "").strip() or None
                out["selected_room_name"] = rname
                return out
    return brief


def _room_target_for_openings(brief: Dict[str, Any]) -> tuple[str | None, str | None]:
    """Room id + name used to scope door/window extraction."""
    rooms = brief.get("rooms_detected") or []
    if not isinstance(rooms, list) or not rooms:
        return None, None
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


def _format_wall_layout_text(brief: Dict[str, Any]) -> str:
    walls = brief.get("wall_assignments") or {}
    if not isinstance(walls, dict):
        return ""
    rows: List[str] = []
    label_for = lambda v: WALL_ITEM_LABELS.get(str(v), str(v).replace("_", " "))
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


def _normalize_rooms_detected_dims(rooms: Any) -> List[Dict[str, Any]]:
    if not isinstance(rooms, list):
        return []
    out: List[Dict[str, Any]] = []
    for r in rooms:
        if not isinstance(r, dict):
            continue
        row = dict(r)
        ln = _num_or_none(row.get("length_m"))
        wd = _num_or_none(row.get("width_m"))
        if ln is not None and wd is not None:
            ln2, wd2 = normalize_dims_to_metres(ln, wd)
            if ln2 is not None:
                row["length_m"] = ln2
            if wd2 is not None:
                row["width_m"] = wd2
        out.append(row)
    return out


def _merge_extracted_floorplan_dims(brief: Dict[str, Any], extracted: Dict[str, Any]) -> Dict[str, Any]:
    """Fills L/W/H from a dedicated floor-plan vision read when the user has not already supplied both L and W."""
    out = dict(brief)
    if not isinstance(extracted, dict) or not extracted.get("readable_from_plan"):
        return out
    ln = _num_or_none(extracted.get("room_length_m"))
    wd = _num_or_none(extracted.get("room_width_m"))
    if ln and wd and not _dims_ok(out):
        ln, wd = normalize_dims_to_metres(ln, wd)
        out["room_length_m"] = ln
        out["room_width_m"] = wd
    ch = _num_or_none(extracted.get("ceiling_height_m"))
    if ch and _num_or_none(out.get("ceiling_height_m")) is None:
        out["ceiling_height_m"] = ch
    return out


_STYLE_HINTS: tuple[str, ...] = (
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

_MOOD_HINTS: tuple[str, ...] = (
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

_BUDGET_BANDS: tuple[str, ...] = (
    "under ₹3 lakh",
    "₹3–8 lakh",
    "₹8–15 lakh",
    "₹15 lakh+",
)


def _user_text_corpus(brief: Dict[str, Any], chat_history: List[Dict[str, str]]) -> str:
    chunks: List[str] = [str(brief.get("notes") or "")]
    mp = brief.get("material_preferences")
    if isinstance(mp, list):
        chunks.extend(str(x) for x in mp if isinstance(x, str) and x.strip())
    for msg in chat_history or []:
        if isinstance(msg, dict) and msg.get("role") == "user":
            chunks.append(str(msg.get("content") or ""))
    return "\n".join(chunks).lower()


def _autofill_missing_brief(
    brief: Dict[str, Any],
    chat_history: List[Dict[str, str]],
    *,
    has_floorplan_image: bool,
) -> Dict[str, Any]:
    """
    Fill missing style / budget / mood / wardrobe from user text when present;
    otherwise pick sensible random defaults. Never blocks on follow-up questions.
    """
    b: Dict[str, Any] = dict(brief)
    corpus = _user_text_corpus(b, chat_history)

    mp = b.get("material_preferences")
    notes_str = str(b.get("notes") or "")
    notes_l = notes_str.lower()
    materials_present = isinstance(mp, list) and len(mp) > 0
    if not materials_present and "materials:" not in notes_l:
        notes_str = (notes_str + ("\n" if notes_str else "") + "Materials: designer's choice.").strip()
        notes_l = notes_str.lower()
        b["notes"] = notes_str

    sd = b.get("style_direction")
    if not (sd and isinstance(sd, str) and sd.strip()):
        picked: str | None = None
        for hint in _STYLE_HINTS:
            if hint in corpus:
                picked = hint
                break
        b["style_direction"] = picked or random.choice(_STYLE_HINTS)

    bb = b.get("budget_band")
    if not (bb and str(bb).strip()):
        band: str | None = None
        for msg in reversed(chat_history or []):
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            text = str(msg.get("content") or "")
            low = text.lower()
            if any(kw in low for kw in ("lakh", "₹", "rs.", "rs ", "inr", "budget")):
                band = text.strip()[:120]
                break
        b["budget_band"] = band or random.choice(_BUDGET_BANDS)

    if "wardrobe style:" not in notes_l:
        wardrobe_style: str | None = None
        if "wardrobe" in corpus:
            for hint in _STYLE_HINTS:
                if hint in corpus:
                    wardrobe_style = hint
                    break
        if not wardrobe_style:
            wardrobe_style = random.choice(_STYLE_HINTS)
        b["notes"] = (
            notes_str + ("\n" if notes_str else "") + f"Wardrobe style: {wardrobe_style}."
        ).strip()

    mk = b.get("mood_keywords")
    has_mood = isinstance(mk, list) and len([k for k in mk if isinstance(k, str) and k.strip()]) > 0
    if not has_mood:
        collected: List[str] = []
        for hint in _MOOD_HINTS:
            if hint in corpus and hint not in collected:
                collected.append(hint)
        if not collected:
            collected = random.sample(list(_MOOD_HINTS), k=min(3, len(_MOOD_HINTS)))
        b["mood_keywords"] = collected

    if has_floorplan_image and not _dims_ok(b):
        b["use_floorplan_image_for_scale_only"] = True

    return b


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


def _finalize_intake_brief(
    brief: Dict[str, Any],
    chat_history: List[Dict[str, str]],
    *,
    has_floorplan_image: bool,
) -> IntakeResponse:
    """Autofill missing preferences; never return follow-up questions."""
    b = _autofill_missing_brief(brief, chat_history, has_floorplan_image=has_floorplan_image)
    return IntakeResponse(is_complete=True, updated_brief=b, questions=[])


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


@app.get("/api/catalog/materials")
def catalog_materials() -> List[Dict[str, Any]]:
    catalog = load_catalog()
    return [
        {
            "id": m.id,
            "name": m.name,
            "unit": m.unit,
            "unit_price": m.unit_price,
        }
        for m in catalog.materials_list()
    ]


@app.post("/api/intake", response_model=IntakeResponse)
def intake(req: IntakeRequest) -> IntakeResponse:
    try:
        cfg = env_config()
        merged_brief = _merge_brief(req.brief)
        floor_imgs = [img.model_dump() for img in req.floorplan_images]

        existing_rooms = merged_brief.get("rooms_detected") or []
        has_rooms = isinstance(existing_rooms, list) and len(existing_rooms) > 0
        if floor_imgs and not has_rooms:
            try:
                rooms = extract_rooms_from_floorplan(cfg=cfg, floorplan_images=floor_imgs)
                if isinstance(rooms, dict) and isinstance(rooms.get("rooms"), list):
                    merged_brief["rooms_detected"] = _normalize_rooms_detected_dims(rooms.get("rooms") or [])
            except Exception:
                pass
        merged_brief = _reconcile_selected_room(merged_brief)

        if floor_imgs and not _dims_ok(merged_brief):
            try:
                extracted = extract_room_dimensions_from_floorplan(cfg=cfg, floorplan_images=floor_imgs)
                merged_brief = _merge_extracted_floorplan_dims(merged_brief, extracted)
            except Exception:
                pass

        if floor_imgs:
            try:
                north_raw = extract_plan_north_from_floorplan(cfg=cfg, floorplan_images=floor_imgs)
                merged_brief = _merge_plan_north(merged_brief, north_raw)
            except Exception:
                logger.warning("extract_plan_north_from_floorplan failed", exc_info=True)

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

        updated = dict(merged_brief)
        updated = _reconcile_selected_room(updated)

        if not _dims_ok(updated):
            extracted = _extract_dims_from_chat([m.model_dump() for m in req.chat_history])
            if extracted:
                updated["room_length_m"] = extracted["room_length_m"]
                updated["room_width_m"] = extracted["room_width_m"]

        return _finalize_intake_brief(
            updated,
            [m.model_dump() for m in req.chat_history],
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
                "In every image_prompt, map each compass wall to a frame position (NORTH=back, EAST=right, WEST=left, SOUTH=near for SW-corner shots) "
                "and state which wall each hero item and door/window is on. Repeat the wall placement verbatim and acknowledge it in the rationale."
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
                + "\n\nIn every image_prompt: describe wall directions in words only (e.g. queen bed on NORTH wall). "
                "Never request a compass rose, logo, watermark, or text overlay in the rendered photograph. "
                "In every rationale: start with 'Layout:' then add 'Compass placement:' repeating the map above item-by-item."
            )
        layout_block = build_mandatory_layout_block(merged_brief)
        if layout_block:
            extra_msgs.append(
                "LOCKED LAYOUT FOR image_prompt (copy this block verbatim at the START of every image_prompt, "
                "then add style/material details after it):\n"
                + layout_block
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
            prompt = enforce_wall_placement_in_prompt(prompt, merged_brief)
            prompt = enhance_image_prompt_for_compass(prompt, merged_brief)
            # Trim style fluff if the combined prompt is huge — keep the locked layout block intact.
            if len(prompt) > 5500 and "MANDATORY FLOOR PLAN LAYOUT" in prompt:
                head, _, tail = prompt.partition(
                    "\n\nSTYLE AND FINISHES (vary materials/colors only — never change wall positions or openings):\n"
                )
                if tail:
                    prompt = head + "\n\nSTYLE AND FINISHES:\n" + tail[:2200]
            rationale = str(d.get("rationale") or "")
            if placement_map and placement_map not in rationale:
                rationale = (rationale.rstrip() + "\n\n" + placement_map).strip()

            image_b64: str | None = None
            if prompt:
                fp_for_img = [img.model_dump() for img in req.floorplan_images]
                imgs = generate_images(
                    cfg=cfg,
                    prompt=prompt,
                    n=1,
                    floorplan_images=fp_for_img if fp_for_img else None,
                )
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

