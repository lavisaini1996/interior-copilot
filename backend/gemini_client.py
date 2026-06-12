from __future__ import annotations

import base64
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from backend.catalog import Catalog, load_catalog
from backend.http_errors import is_network_error
from backend.moodboard_walls import moodboard_plan_schema
from backend.wall_placement import build_layout_qa_checklist

logger = logging.getLogger("interior_copilot.gemini")

T = TypeVar("T")


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str
    text_model: str = "gemini-2.5-flash"
    text_model_fallback: str = ""
    image_model: str = "imagen-4.0-generate-001"


def _client(cfg: GeminiConfig) -> genai.Client:
    return genai.Client(api_key=cfg.api_key)


def env_config() -> GeminiConfig:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Missing GEMINI_API_KEY. Create a .env file (see .env.example) or set it in your environment."
        )
    return GeminiConfig(
        api_key=api_key,
        text_model=os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash").strip(),
        text_model_fallback=os.environ.get("GEMINI_TEXT_MODEL_FALLBACK", "gemini-2.0-flash").strip(),
        image_model=os.environ.get("GEMINI_IMAGE_MODEL", "imagen-4.0-generate-001").strip(),
    )


_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def _image_gen_failure_is_expected(exc: BaseException) -> bool:
    """
    Imagen is often unavailable on free AI Studio / API keys (paid plan required).
    In those cases we degrade gracefully: return no image bytes instead of failing the whole request.
    """
    if isinstance(exc, genai_errors.ClientError):
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        try:
            c = int(code)
        except (TypeError, ValueError):
            c = None
        msg = str(exc).lower()
        if c == 403:
            return True
        if c == 400 and any(
            x in msg
            for x in (
                "paid plan",
                "paid plans",
                "billing",
                "permission",
                "imagen",
                "not enabled",
                "not available",
            )
        ):
            return True
    return False


def _is_transient(exc: BaseException) -> bool:
    """Server overloads, rate limits, and gateway hiccups are worth retrying."""
    if isinstance(exc, genai_errors.ServerError):
        return True
    if isinstance(exc, genai_errors.ClientError):
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        try:
            return int(code) in _TRANSIENT_STATUS
        except (TypeError, ValueError):
            return False
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        try:
            return int(code) in _TRANSIENT_STATUS
        except (TypeError, ValueError):
            return False
    return False


def _with_retries(fn: Callable[[], T], *, what: str, attempts: int = 5, base_delay: float = 1.5) -> T:
    """Retry transient Gemini errors (503/429/etc.) with exponential backoff + jitter."""
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if (not _is_transient(e) and not is_network_error(e)) or i == attempts - 1:
                raise
            delay = base_delay * (2**i) + random.uniform(0, 0.5)
            logger.warning("Gemini %s transient error (attempt %d/%d): %s. Retrying in %.1fs", what, i + 1, attempts, e, delay)
            time.sleep(delay)
    assert last is not None
    raise last


def _parts_from_system_payload_and_images(
    *, system_text: str, user_json_payload: Dict[str, Any], context_images: List[Dict[str, str]] | None
) -> List[types.Part]:
    parts: List[types.Part] = [
        types.Part.from_text(text=system_text + "\n\n" + json.dumps(user_json_payload, ensure_ascii=False))
    ]
    for img in context_images or []:
        mime = (img.get("mime_type") or "").strip()
        data_b64 = (img.get("data_base64") or "").strip()
        if not mime or not data_b64:
            continue
        raw = base64.b64decode(data_b64)
        parts.append(types.Part.from_bytes(data=raw, mime_type=mime))
    return parts


def _generate_json(
    *,
    cfg: GeminiConfig,
    system_text: str,
    user_json_payload: Dict[str, Any],
    context_images: List[Dict[str, str]] | None,
    schema: Dict[str, Any],
    temperature: float,
) -> Dict[str, Any]:
    client = _client(cfg)
    parts = _parts_from_system_payload_and_images(
        system_text=system_text, user_json_payload=user_json_payload, context_images=context_images
    )
    cfg_obj = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
        temperature=temperature,
    )

    def _call(model_name: str):
        return client.models.generate_content(
            model=model_name,
            contents=[types.Content(role="user", parts=parts)],
            config=cfg_obj,
        )

    models_to_try: List[str] = [cfg.text_model]
    if cfg.text_model_fallback and cfg.text_model_fallback != cfg.text_model:
        models_to_try.append(cfg.text_model_fallback)

    resp = None
    last_exc: BaseException | None = None
    for idx, model_name in enumerate(models_to_try):
        try:
            resp = _with_retries(lambda m=model_name: _call(m), what=f"generate_content({model_name})")
            break
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if idx < len(models_to_try) - 1 and _is_transient(e):
                logger.warning("Primary model %s unavailable, falling back to %s: %s", model_name, models_to_try[idx + 1], e)
                continue
            raise
    if resp is None:
        assert last_exc is not None
        raise last_exc

    try:
        data = json.loads(resp.text or "{}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Model returned non-JSON output: {resp.text}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected JSON shape (expected object): {data}")
    return data


def extract_room_dimensions_from_floorplan(
    *, cfg: GeminiConfig, floorplan_images: List[Dict[str, str]]
) -> Dict[str, Any]:
    if not floorplan_images:
        return {
            "room_length_m": None,
            "room_width_m": None,
            "ceiling_height_m": None,
            "readable_from_plan": False,
            "notes": "",
        }

    system = (
        "You read architectural floor plans. Extract numeric room dimensions that are PRINTED or clearly dimensioned "
        "on the drawing (overall room length and width for the main space the plan depicts). "
        "Output values in metres. Convert from feet/inches, millimetres, or a printed scale bar only when it clearly "
        "yields those dimensions; otherwise return nulls. "
        "If ceiling height appears on a section or note, return it; else null. "
        "If nothing is confidently readable, set readable_from_plan=false and do not guess. "
        "Output ONLY valid JSON matching the schema."
    )

    schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "room_length_m": {"type": "number", "nullable": True},
            "room_width_m": {"type": "number", "nullable": True},
            "ceiling_height_m": {"type": "number", "nullable": True},
            "readable_from_plan": {"type": "boolean"},
            "notes": {"type": "string"},
        },
        "required": ["room_length_m", "room_width_m", "ceiling_height_m", "readable_from_plan", "notes"],
    }

    return _generate_json(
        cfg=cfg,
        system_text=system,
        user_json_payload={"task": "extract_room_dimensions_metres"},
        context_images=floorplan_images,
        schema=schema,
        temperature=0.1,
    )


def extract_rooms_from_floorplan(*, cfg: GeminiConfig, floorplan_images: List[Dict[str, str]]) -> Dict[str, Any]:
    if not floorplan_images:
        return {"rooms": [], "notes": ""}

    system = (
        "You read architectural floor plans for an entire home. Identify distinct rooms/spaces that are labeled "
        "(e.g., Bedroom, Living, Kitchen, Study) and extract their printed dimensions when visible. "
        "Output all dimensions in metres. When the plan shows feet/inches (e.g. 10' x 12', 13'-2\"), convert to metres "
        "(multiply feet by 0.3048). Never store raw foot numbers in length_m/width_m without converting. "
        "If a room's dimensions are not readable, set them to null. Do not guess. "
        "Return a compact list of rooms that a user could pick from to generate a design."
    )

    schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "rooms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "length_m": {"type": "number", "nullable": True},
                        "width_m": {"type": "number", "nullable": True},
                        "area_m2": {"type": "number", "nullable": True},
                    },
                    "required": ["id", "name", "length_m", "width_m", "area_m2"],
                },
            },
            "notes": {"type": "string"},
        },
        "required": ["rooms", "notes"],
    }

    return _generate_json(
        cfg=cfg,
        system_text=system,
        user_json_payload={"task": "extract_rooms_and_dimensions_metres"},
        context_images=floorplan_images,
        schema=schema,
        temperature=0.1,
    )


def extract_plan_north_from_floorplan(
    *, cfg: GeminiConfig, floorplan_images: List[Dict[str, str]]
) -> Dict[str, Any]:
    """
    Detect plan north: degrees clockwise from the TOP of the image to true/plan north.
    Uses a north arrow, letter N, or similar symbol when present; otherwise 0°.
    """
    if not floorplan_images:
        return {"north_clockwise_deg": 0.0, "has_north_indicator": False, "notes": ""}

    system = (
        "You read architectural floor plans. Determine which direction is geographic/plan NORTH on the drawing.\n"
        "Output north_clockwise_deg: degrees to rotate CLOCKWISE from the TOP edge of the image so that direction "
        "points to north (0 = top of image is north; 90 = right edge is north; 180 = bottom is north; 270 = left is north).\n"
        "Look for a north arrow, letter N, compass rose, or an explicit 'NORTH' label on the sheet.\n"
        "Measure north_clockwise_deg from the TOP of the image to the direction the arrow points (clockwise).\n"
        "If there is no reliable north symbol, set has_north_indicator=false and north_clockwise_deg=0.\n"
        "Do not guess from furniture layout or room labels alone. Output ONLY valid JSON matching the schema."
    )

    schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "north_clockwise_deg": {"type": "number"},
            "has_north_indicator": {"type": "boolean"},
            "notes": {"type": "string"},
        },
        "required": ["north_clockwise_deg", "has_north_indicator", "notes"],
    }

    return _generate_json(
        cfg=cfg,
        system_text=system,
        user_json_payload={"task": "detect_plan_north_clockwise_from_image_top"},
        context_images=floorplan_images,
        schema=schema,
        temperature=0.1,
    )


def extract_wall_openings_from_floorplan(
    *,
    cfg: GeminiConfig,
    floorplan_images: List[Dict[str, str]],
    target_room_id: str | None = None,
    target_room_name: str | None = None,
    rooms_detected: List[Dict[str, Any]] | None = None,
    north_from_image_up_clockwise_deg: float = 0.0,
) -> Dict[str, Any]:
    """
    Vision pass: doors, windows, and similar openings on each compass wall of the target room.
    Walls are labeled N/S/E/W using orientation: clockwise degrees from the TOP of the image to true/plan north.
    """
    if not floorplan_images:
        return {
            "wall_openings": {"north": [], "south": [], "east": [], "west": []},
            "notes": "",
        }

    try:
        d = float(north_from_image_up_clockwise_deg) % 360.0
    except (TypeError, ValueError):
        d = 0.0

    system = (
        "You read architectural floor plans. Identify DOORS and WINDOWS (and balcony sliders / glazed doors) on the "
        "TARGET ROOM's boundary walls only.\n"
        "\n"
        "CRITICAL: The plan has multiple rooms. You MUST first find the exact target room by reading the room label text "
        "(e.g. 'BED ROOM -1' vs 'BED ROOM -2' vs 'M.BED ROOM'). If you cannot confidently find the exact label for the target "
        "room, return empty lists for all walls and explain in notes. Do NOT guess.\n"
        "CRITICAL: Only include openings that TOUCH the target room's perimeter wall. Never include openings from adjacent rooms, "
        "even if they are nearby.\n"
        "CRITICAL: You will be given a list of detected room labels. Any opening destination you mention (e.g. 'to Toilet 5'0\"×9'0\"') "
        "MUST match one of those labels, and it MUST be a room that shares a boundary with the target room. If it doesn't share a wall, "
        "exclude it.\n"
        "Step 1 — Find plan NORTH from the north arrow, letter N, or compass rose ON THE DRAWING (primary source).\n"
        "Step 2 — Locate the target room (match target_room_name / id).\n"
        "Step 3 — For each opening on that room's perimeter, assign north/south/east/west using the sheet's north arrow.\n"
        f"User orientation hint (use ONLY if the sheet has no north symbol): rotate CLOCKWISE from the TOP of the image "
        f"by {d:.0f}° to get plan north (0=top is north, 90=right is north, 180=bottom, 270=left is north).\n"
        "If a north arrow on the sheet disagrees with the hint, TRUST THE ARROW on the sheet.\n"
        "Each list entry MUST be one phrase including:\n"
        "- opening type (door / window / sliding door / glazed door)\n"
        "- labeled destination when shown on plan (e.g. 'to Hallway', 'to Walk-in Closet', 'to Balcony') — read text labels on the plan\n"
        "- position on that wall (left / center / right OR upper / lower half)\n"
        "Examples: 'swing door to Walk-in Closet, left side of wall'; 'swing door to Hallway, upper half'; "
        "'two-panel sliding glass door to Balcony, centered'.\n"
        "\n"
        "Self-check before output: verify every opening you list is physically drawn on the boundary of the target room label you found. "
        "If an opening is on a different room (e.g. Dining balcony slider), do not include it.\n"
        "Do not invent openings. Do not move a door to a different wall than drawn. Empty array if none on that wall.\n"
        "Output ONLY valid JSON matching the schema."
    )

    schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "target_room_label_found": {"type": "boolean"},
            "target_room_label_text": {"type": "string"},
            "wall_openings": {
                "type": "object",
                "properties": {
                    "north": {"type": "array", "items": {"type": "string"}},
                    "south": {"type": "array", "items": {"type": "string"}},
                    "east": {"type": "array", "items": {"type": "string"}},
                    "west": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["north", "south", "east", "west"],
            },
            "notes": {"type": "string"},
        },
        "required": ["target_room_label_found", "target_room_label_text", "wall_openings", "notes"],
    }

    payload = {
        "task": "extract_doors_windows_per_wall",
        "target_room_id": target_room_id,
        "target_room_name": target_room_name,
        "rooms_detected": rooms_detected or [],
        "north_from_image_up_clockwise_deg": d,
    }

    return _generate_json(
        cfg=cfg,
        system_text=system,
        user_json_payload=payload,
        context_images=floorplan_images,
        schema=schema,
        temperature=0.1,
    )


def generate_next_questions(
    *,
    cfg: GeminiConfig,
    brief: Dict[str, Any],
    chat_history: List[Dict[str, str]],
    context_images: List[Dict[str, str]] | None = None,
    max_questions: int = 3,
) -> Dict[str, Any]:
    system = (
        "You are an interior design intake assistant for a floor-plan-based room designer. "
        "All budgets and catalog pricing are in Indian Rupees (INR).\n"
        "Your job is to ask concise follow-up questions until the brief is sufficient to generate measured, catalog-constrained design images.\n"
        "Rules:\n"
        f"- Ask at most {max_questions} questions.\n"
        "- Each question should bundle multiple missing fields to minimize back-and-forth.\n"
        "- If the user uploads a floor plan or reference image but sends little or no text, you MUST still ask follow-ups "
        "for anything not already readable on the images (style, materials, budget in INR; doors/windows only if relevant).\n"
        "- When a floor plan image is present, READ printed dimensions, dimension strings, and scale from the drawing first. "
        "Populate room_length_m, room_width_m, and ceiling_height_m (metres) whenever they are clearly shown—do not ask the user "
        "to repeat length/width if those values are already on the plan. Convert feet/inches or mm to metres when needed.\n"
        "- Do not mark is_complete=true until numeric room_length_m and room_width_m are known (from chat OR from the plan image), "
        "OR the user explicitly opts in via chat to use only the drawing for proportions (set use_floorplan_image_for_scale_only=true).\n"
        "- If enough info is present, ask zero questions and set is_complete=true.\n"
        "- Prefer multiple-choice style questions when possible.\n"
        "- Update the brief by extracting any new facts from the chat history and from images (only when reasonably inferable).\n"
        "- Output ONLY valid JSON matching the schema."
    )

    brief_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "space_type": {"type": "string", "nullable": True},
            "style_direction": {"type": "string", "nullable": True},
            "mood_keywords": {"type": "array", "items": {"type": "string"}},
            "color_preferences": {"type": "array", "items": {"type": "string"}},
            "material_preferences": {"type": "array", "items": {"type": "string"}},
            "budget_band": {"type": "string", "nullable": True},
            "must_include": {"type": "array", "items": {"type": "string"}},
            "must_avoid": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "string"},
            "room_length_m": {"type": "number", "nullable": True},
            "room_width_m": {"type": "number", "nullable": True},
            "ceiling_height_m": {"type": "number", "nullable": True},
            "use_floorplan_image_for_scale_only": {"type": "boolean"},
            "rooms_detected": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "length_m": {"type": "number", "nullable": True},
                        "width_m": {"type": "number", "nullable": True},
                        "area_m2": {"type": "number", "nullable": True},
                    },
                    "required": ["id", "name", "length_m", "width_m", "area_m2"],
                },
            },
            "selected_room_id": {"type": "string", "nullable": True},
            "selected_room_name": {"type": "string", "nullable": True},
            "wall_assignments": {
                "type": "object",
                "properties": {
                    "north": {"type": "array", "items": {"type": "string"}},
                    "south": {"type": "array", "items": {"type": "string"}},
                    "east": {"type": "array", "items": {"type": "string"}},
                    "west": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["north", "south", "east", "west"],
            },
        },
        "required": [
            "space_type",
            "style_direction",
            "mood_keywords",
            "color_preferences",
            "material_preferences",
            "budget_band",
            "must_include",
            "must_avoid",
            "notes",
            "room_length_m",
            "room_width_m",
            "ceiling_height_m",
            "use_floorplan_image_for_scale_only",
            "rooms_detected",
            "selected_room_id",
            "selected_room_name",
            "wall_assignments",
        ],
    }

    schema = {
        "type": "object",
        "properties": {
            "is_complete": {"type": "boolean"},
            "updated_brief": brief_schema,
            "questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["is_complete", "updated_brief", "questions"],
    }

    payload = {
        "brief": brief,
        "chat_history": chat_history,
        "has_reference_images": bool(context_images),
        "minimum_required_fields": [
            "space_type",
            "style_direction",
            "mood_keywords",
            "color_preferences",
            "material_preferences",
            "budget_band",
            "must_include",
            "must_avoid",
            "room_length_m",
            "room_width_m",
            "ceiling_height_m",
            "use_floorplan_image_for_scale_only",
        ],
        "note": "If a field is unknown, keep it null or empty. Do not invent numeric dimensions: use only values the user stated "
        "or that are clearly readable on an uploaded floor plan. Never ask the user for room length/width when a floor plan image "
        "is attached and those dimensions are already visible on it—extract them into the brief instead.",
    }

    data = _generate_json(
        cfg=cfg,
        system_text=system,
        user_json_payload=payload,
        context_images=context_images,
        schema=schema,
        temperature=0.4,
    )

    qs = data.get("questions")
    if isinstance(qs, list):
        data["questions"] = [q for q in qs if isinstance(q, str)][:max_questions]
    return data


def generate_moodboard_prompts(
    *, cfg: GeminiConfig, brief: Dict[str, Any], n: int = 3, context_images: List[Dict[str, str]] | None = None
) -> List[str]:
    system = (
        "You generate high-quality image prompts for an interior design moodboard. "
        "Prompts should be photorealistic, interior-design specific, and consistent with the brief. "
        "Return ONLY JSON that matches the provided schema."
    )

    schema = {
        "type": "object",
        "properties": {
            "prompts": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["prompts"],
    }

    payload = {"brief": brief, "num_prompts": n}
    obj = _generate_json(
        cfg=cfg,
        system_text=system,
        user_json_payload=payload,
        context_images=context_images,
        schema=schema,
        temperature=0.7,
    )
    prompts = obj.get("prompts")
    if not isinstance(prompts, list) or not all(isinstance(x, str) for x in prompts):
        raise RuntimeError(f"Unexpected prompts shape: {obj}")
    return prompts[:n]


def plan_moodboard_wall_panels(
    *,
    cfg: GeminiConfig,
    brief: Dict[str, Any],
    variants_per_wall: int = 3,
    context_images: List[Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    """
    Plan Mr Dileep–style moodboard: one section per compass wall (and ceiling/overview when relevant),
    each with 3–4 component variants and photorealistic image prompts.
    """
    n_var = max(1, min(4, int(variants_per_wall)))
    room = str(brief.get("selected_room_name") or brief.get("space_type") or "room").strip()
    system = (
        "You plan interior design moodboards like a professional component deck (one image per component).\n"
        "Example titles: 'Sofa — South wall', 'TV unit — North wall', 'Coffee table — floor', 'Dining table — floor'.\n"
        "Given a room brief with compass wall assignments, produce panels for each assigned item on each wall.\n"
        "- REQUIRED: one panel per component in brief.wall_assignments (sofa, tv_unit, wardrobe, etc.) — never bundle "
        "multiple components into one panel.\n"
        "- REQUIRED zone_id 'floor' panels for standard center-floor items (coffee table, dining table, bed, rug) "
        "when not already on a wall.\n"
        "- Optional zone_id 'ceiling' (false ceiling / lighting); skip zone_id 'overview'.\n"
        f"Each component panel must include exactly {n_var} variants (Option A/B/C…) — different materials, "
        "silhouettes, or finishes for the SAME component, not different components bundled together.\n"
        "CRITICAL — one component per image:\n"
        "- Every component image must include its zone background (wall finish, floor, lighting) — not a plain studio backdrop.\n"
        "- Sofa/sectional: hero sofa in front of the styled wall behind it — NOT a full furnished living room.\n"
        "- TV unit / accent wall: feature wall with materials and lighting — NOT a whole-room panorama.\n"
        "- Coffee table / dining table / bed: hero item on styled floor with partial wall context — NOT a full room layout.\n"
        "- List floor items in suggested_floor_items.\n"
        "Each image_prompt must describe exactly ONE catalog component with materials and style.\n"
        "If brief.wall_assignments are all empty, fill suggested_wall_assignments with sensible defaults.\n"
        "Output ONLY valid JSON matching the schema."
    )
    payload = {
        "brief": brief,
        "room_name": room,
        "variants_per_panel": n_var,
        "zone_ids": ["north", "south", "east", "west", "ceiling", "overview"],
    }
    obj = _generate_json(
        cfg=cfg,
        system_text=system,
        user_json_payload=payload,
        context_images=context_images,
        schema=moodboard_plan_schema(),
        temperature=0.55,
    )
    if not isinstance(obj, dict):
        raise RuntimeError(f"Unexpected moodboard plan shape: {obj}")
    return obj


def _extract_image_bytes_from_content_response(resp: Any) -> List[bytes]:
    out: List[bytes] = []
    for cand in resp.candidates or []:
        content = getattr(cand, "content", None)
        if not content:
            continue
        for part in content.parts or []:
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                out.append(bytes(inline.data))
    return out


def generate_images_with_floorplan(
    *,
    cfg: GeminiConfig,
    prompt: str,
    floorplan_images: List[Dict[str, str]],
    n: int = 1,
) -> List[bytes]:
    """
    Generate a room render using Gemini native image output + floor plan reference.
    Falls back to empty list on failure so callers can use Imagen.
    """
    native_model = os.environ.get("GEMINI_NATIVE_IMAGE_MODEL", "gemini-2.5-flash-image").strip()
    if not native_model or not floorplan_images:
        return []

    client = _client(cfg)
    intro = (
        "Render one photorealistic interior photo. The FIRST attached image is the floor plan (authoritative).\n"
        "Read the text starting with '=== DIRECTOR MANDATE ===' and match it exactly before applying style.\n"
        "If the DIRECTOR says bed on the FAR/BACK (NORTH) wall: the bed headboard must be on the deepest wall "
        "in frame (view from south doorway), NOT on the left or right side walls.\n"
        "TV on WEST = left wall only. Doors/windows only on walls listed. No extra openings.\n"
        "No logo, watermark, or compass overlay.\n\n"
    )
    parts: List[types.Part] = [types.Part.from_text(text=intro + prompt)]
    for img in floorplan_images[:1]:
        mime = (img.get("mime_type") or "").strip()
        data_b64 = (img.get("data_base64") or "").strip()
        if not mime or not data_b64:
            continue
        parts.append(types.Part.from_bytes(data=base64.b64decode(data_b64), mime_type=mime))

    if len(parts) < 2:
        return []

    config = types.GenerateContentConfig(
        response_modalities=["IMAGE", "TEXT"],
        temperature=0.1,
    )

    def _call():
        return client.models.generate_content(
            model=native_model,
            contents=[types.Content(role="user", parts=parts)],
            config=config,
        )

    try:
        resp = _with_retries(_call, what=f"generate_content({native_model})")
        return _extract_image_bytes_from_content_response(resp)[:n]
    except Exception as e:  # noqa: BLE001
        logger.warning("Gemini floor-plan image generation failed (%s): %s", native_model, e)
        return []


def generate_images(
    *,
    cfg: GeminiConfig,
    prompt: str,
    n: int = 1,
    floorplan_images: List[Dict[str, str]] | None = None,
) -> List[bytes]:
    if floorplan_images:
        target = max(1, n)
        out: List[bytes] = []
        max_tries = target + 2
        tries = 0
        while len(out) < target and tries < max_tries:
            tries += 1
            batch = generate_images_with_floorplan(
                cfg=cfg, prompt=prompt, floorplan_images=floorplan_images, n=1
            )
            if batch:
                out.extend(batch)
        if out:
            return out[:target]

    if not (cfg.image_model or "").strip():
        return []

    client = _client(cfg)

    def _call():
        return client.models.generate_images(
            model=cfg.image_model,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=n,
                output_mime_type="image/png",
            ),
        )

    try:
        resp = _with_retries(_call, what=f"generate_images({cfg.image_model})")
    except Exception as e:  # noqa: BLE001
        if _is_transient(e) or _image_gen_failure_is_expected(e):
            logger.warning("Image generation skipped for this option: %s", e)
            return []
        raise
    out: List[bytes] = []
    for gi in (resp.generated_images or []):
        if gi.image and gi.image.image_bytes:
            out.append(gi.image.image_bytes)
    return out


def score_render_wall_layout(
    *,
    cfg: GeminiConfig,
    rendered_png_bytes: bytes,
    locked_layout_text: str,
    brief: Dict[str, Any] | None = None,
) -> tuple[bool, int, List[str]]:
    """
    Vision QA with 0–10 score. ok=true only when layout is clearly correct (score >= 8).
    """
    if not rendered_png_bytes or not locked_layout_text.strip():
        return True, 10, []

    system = (
        "You are a strict QA checker for interior renders.\n"
        "You will be given (A) a LOCKED LAYOUT spec that defines which furniture/openings must be on each compass wall "
        "and how those compass walls map to physical walls in the photo frame (back/left/right/near), and (B) a single "
        "rendered interior image.\n"
        "Task: score how well the IMAGE matches the LOCKED LAYOUT (0=wrong layout, 10=perfect).\n"
        "Fail (ok=false, score<=7) if any hero item is on the wrong wall or doors/windows are on the wrong wall.\n"
        "CRITICAL: Use the LOCKED LAYOUT's spatial map to determine which wall is back/left/right in the photo. "
        "Fail when the bed headboard is not flush on the assigned NORTH wall (wherever NORTH appears in the spatial map).\n"
        "CRITICAL: If the TV is assigned to the WEST wall, fail when the TV is not on the left wall.\n"
        "CRITICAL: If a window is labeled centered on the NORTH wall, fail when it is a narrow strip to the left/right "
        "of the bed instead of centered on the far wall.\n"
        "CRITICAL: Fail if extra windows appear on walls with no openings listed, or if opening horizontal position "
        "(left/center/right) does not match the spec.\n"
        "Set ok=true only when score is 8 or higher and you are confident.\n"
        "Output ONLY valid JSON matching the schema."
    )
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "score": {"type": "integer"},
            "reasons": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["ok", "score", "reasons"],
    }
    checklist = build_layout_qa_checklist(brief or {})
    if not checklist:
        checklist = [
            "Every item listed on a compass wall must be physically placed on that wall in the photo (per spatial map).",
            "Every opening listed must be on that compass wall in the photo.",
            "No rotation/mirroring: left/right walls must match the spatial map.",
        ]
    payload = {
        "locked_layout": locked_layout_text,
        "checklist": checklist,
    }
    img_payload = {
        "mime_type": "image/png",
        "data_base64": base64.b64encode(rendered_png_bytes).decode("utf-8"),
    }
    try:
        obj = _generate_json(
            cfg=cfg,
            system_text=system,
            user_json_payload=payload,
            context_images=[img_payload],
            schema=schema,
            temperature=0.0,
        )
        reasons = [str(x) for x in (obj.get("reasons") or []) if isinstance(x, str)]
        try:
            score = int(obj.get("score"))
        except (TypeError, ValueError):
            score = 10 if obj.get("ok") else 0
        score = max(0, min(10, score))
        ok = bool(obj.get("ok")) and score >= 8
        return ok, score, reasons
    except Exception as e:  # noqa: BLE001
        logger.warning("Render layout verification failed (treating as not-ok): %s", e)
        return False, 0, [str(e)]


def verify_render_matches_wall_layout(
    *,
    cfg: GeminiConfig,
    rendered_png_bytes: bytes,
    locked_layout_text: str,
    brief: Dict[str, Any] | None = None,
) -> bool:
    ok, _, _ = score_render_wall_layout(
        cfg=cfg,
        rendered_png_bytes=rendered_png_bytes,
        locked_layout_text=locked_layout_text,
        brief=brief,
    )
    return ok


def _catalog_payload(catalog: Catalog) -> Dict[str, Any]:
    return {
        "currency": catalog.currency,
        "note": f"All catalog item prices and material unit_price values are in {catalog.currency} (Indian Rupees).",
        "materials": [
            {
                "id": m.id,
                "name": m.name,
                "unit": m.unit,
                "unit_price": m.unit_price,
            }
            for m in catalog.materials_list()
        ],
        "items": [
            {
                "id": it.id,
                "name": it.name,
                "category": it.category,
                "price": it.price,
                "material_ids": list(it.material_ids),
            }
            for it in catalog.items_list()
        ],
    }


def generate_catalog_designs(
    *,
    cfg: GeminiConfig,
    brief: Dict[str, Any],
    chat_history: List[Dict[str, str]] | None = None,
    floorplan_text: str | None = None,
    floorplan_images: List[Dict[str, str]] | None = None,
    style_reference_images: List[Dict[str, str]] | None = None,
    num_designs: int = 3,
) -> Dict[str, Any]:
    catalog = load_catalog()

    system = (
        "You are an interior designer generating concrete design options from a floor plan. "
        "You MUST only use items that exist in the provided catalog. "
        "You MUST NOT invent SKUs, brand names, or prices. "
        "All money values in the catalog are in Indian Rupees (INR).\n"
        "Use the brief's room_length_m, room_width_m, and ceiling_height_m (metres) when present; repeat them verbatim in every image_prompt. "
        "If use_floorplan_image_for_scale_only is true and dimensions are missing, describe proportions consistent with the attached floor plan image "
        "and state that dimensions are inferred from the drawing (no numeric room size).\n"
        "Compute material quantities from the room where applicable (e.g. floor finish m² ≈ length×width; paint litres ≈ (perimeter×height)/coverage rule of thumb ~0.12 L/m² per coat for estimation, use 2 coats unless brief says otherwise).\n"
        "You MUST vary the three options: do not return the same sofa (primary seating) across all options, and keep each option visually distinct.\n"
        "Budget rule: use brief.budget_band (INR) to scale how many items and how premium they are. "
        "For low budgets, pick fewer/lower-cost SKUs; for high budgets, include more items/finishes from the catalog.\n"
        "Material rule: if brief.material_preferences is set (e.g. wood/metal/linen/leather/stone), prefer catalog items/materials that align.\n"
        "If a material preference is provided (example: stone), at least one major visible element MUST use it when available in the catalog "
        "(e.g. stone-top bedside, stone accent wall). If it cannot be satisfied with the catalog, say so in the rationale and pick the closest match.\n"
        "Wall placement rule: when brief.wall_assignments or brief.wall_openings is provided, or when chat contains 'WALL LAYOUT' or 'LOCKED LAYOUT', you MUST copy the LOCKED LAYOUT block verbatim at the start of every image_prompt, then add style/material details after it. Never move furniture or doors/windows to a different compass wall.\n"
        "Opening rule: when brief.wall_openings lists doors, windows, sliders, or glazing on a compass wall, keep them on that wall only; furniture must not block those openings.\n"
        "Anti-hallucination: do not invent extra walls, doors, windows, or furniture positions that contradict the locked layout.\n"
        "Pick concrete catalog SKUs that match each requested item type (e.g. for 'wardrobe' choose a catalog wardrobe; for 'bed' choose a catalog bed; for 'tv_unit' choose a catalog TV unit). If a requested item type has no matching catalog item, mention the gap in the rationale and select the closest substitute.\n"
        "Camera rule: when the assignment lists items on OPPOSING walls (north+south, or east+west), the image_prompt MUST describe a two-point/corner camera (e.g. 'wide-angle two-point perspective from the south-west corner looking toward the north-east, ~24mm equivalent') so BOTH opposing walls are visible in the rendered frame. Do not use a straight-on one-wall elevation when opposing walls are assigned. Mention the camera angle and which walls are visible in the image_prompt.\n"
        "Spatial rule: after the LOCKED LAYOUT block, state where each compass wall appears in the frame (e.g. 'NORTH wall = back wall with bed; EAST wall = right wall with door to hallway'). Name every hero item with its wall AND its frame position (back/left/right/near).\n"
        "Rationale rule: the rationale MUST start with a one-line 'Layout:' summary listing each wall and what is on it (e.g. 'Layout: North—bed + sconces; South—TV unit; East—accent wall; West—wardrobe.'). "
        "Then add a 'Compass placement:' section that names EVERY major catalog item with its compass wall (NORTH/SOUTH/EAST/WEST) so the user can verify against their wall picker.\n"
        "Image render rule: photorealistic room only — NO logo, watermark, compass rose, north arrow, text overlay, or corner badge in the image. "
        "State wall directions (NORTH/SOUTH/EAST/WEST) in the prompt text and rationale only, never drawn on the photograph. "
        "The rendered photo must show furniture and openings on the correct physical walls, not just mention them in text.\n"
        "If some style/material preferences are missing, assume warm minimal, light neutrals, natural wood + black accents.\n"
        "Output ONLY valid JSON matching the schema. No markdown."
    )

    schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "designs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "rationale": {"type": "string"},
                        "catalog_item_ids": {"type": "array", "items": {"type": "string"}},
                        "materials": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "material_id": {"type": "string"},
                                    "name": {"type": "string"},
                                    "unit": {"type": "string"},
                                    "unit_price": {"type": "number"},
                                    "quantity": {"type": "number"},
                                },
                                "required": ["material_id", "name", "unit", "unit_price", "quantity"],
                            },
                        },
                        "image_prompt": {"type": "string"},
                    },
                    "required": ["title", "rationale", "catalog_item_ids", "materials", "image_prompt"],
                },
            }
        },
        "required": ["designs"],
    }

    context_images: List[Dict[str, str]] = []
    for img in floorplan_images or []:
        context_images.append(img)
    for img in style_reference_images or []:
        context_images.append(img)

    payload: Dict[str, Any] = {
        "brief": brief,
        "chat_history": chat_history or [],
        "floorplan_text": (floorplan_text or "").strip(),
        "has_floorplan_image": bool(floorplan_images),
        "catalog": _catalog_payload(catalog),
        "num_designs": max(2, min(5, int(num_designs))),
        "rules": [
            "Select catalog_item_ids ONLY from catalog.items[].id",
            "Choose a coherent set of items that fit the floor plan and style",
            "Materials must reference catalog.materials[].id and include quantity and unit_price",
            "All design options must be meaningfully different in key choices (at minimum: different sofa SKU, different lighting or rug choice)",
            "Use the user's budget_band to constrain the overall selection; cheaper budget → fewer/cheaper SKUs",
            "Prefer describing realistic placement (e.g. sofa along longest wall, rug under seating group)",
            "Image prompts must be photorealistic, interior-specific, name each selected catalog item, and state room dimensions L×W×H in metres when available",
            "Image prompts must describe camera angle and layout so the rendered room matches the stated proportions",
            "If brief.wall_assignments or brief.wall_openings has any non-empty arrays, every image_prompt MUST start with the LOCKED LAYOUT block from chat (if present) and the rationale MUST acknowledge the wall layout explicitly",
            "Never contradict user wall_assignments or wall_openings — if unsure, repeat the locked layout verbatim rather than inventing a new plan",
        ],
    }

    return _generate_json(
        cfg=cfg,
        system_text=system,
        user_json_payload=payload,
        context_images=context_images,
        schema=schema,
        temperature=0.35,
    )
