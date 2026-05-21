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
        "Output all dimensions in metres, converting from feet/inches or mm only if the printed values are clear. "
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


def extract_wall_openings_from_floorplan(
    *,
    cfg: GeminiConfig,
    floorplan_images: List[Dict[str, str]],
    target_room_id: str | None = None,
    target_room_name: str | None = None,
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
        "You read architectural floor plans. Identify DOORS and WINDOWS (and balcony sliders / glazed doors) that "
        "belong to the TARGET ROOM's boundary walls only. Ignore openings in adjacent rooms unless they clearly sit on a "
        "shared wall segment of the target room.\n"
        "For each opening, assign it to exactly one compass wall of the room: north, south, east, or west.\n"
        "Compass rule: treat geographic/plan NORTH as the direction found by rotating CLOCKWISE from the TOP of the image "
        f"by {d:.0f} degrees. (0° = image top is north; 90° = image right edge is north; 180° = image bottom is north; "
        "270° = image left edge is north.) If the sheet shows a north arrow that clearly disagrees with this mapping, "
        "still follow this compass rule so labels stay consistent with the user's orientation control.\n"
        "Each list entry should be a short human-readable phrase, e.g. "
        "'single swing door, left third of wall', 'two-panel sliding window, centred', 'full-height glazing wall'.\n"
        "If an opening type is uncertain, describe what you see (e.g. 'opening with arc swing — likely door'). "
        "If nothing is visible for a wall, use an empty array. Do not invent openings. "
        "Output ONLY valid JSON matching the schema."
    )

    schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
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
        "required": ["wall_openings", "notes"],
    }

    payload = {
        "task": "extract_doors_windows_per_wall",
        "target_room_id": target_room_id,
        "target_room_name": target_room_name,
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


def generate_images(*, cfg: GeminiConfig, prompt: str, n: int = 1) -> List[bytes]:
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
        "Wall placement rule: when brief.wall_assignments is provided (object with arrays for north/south/east/west walls), or when the chat history contains a message starting with 'WALL LAYOUT', each listed item type MUST be placed visibly along the named wall AND explicitly mentioned in the image_prompt (e.g. 'bed centred on the north wall with upholstered headboard; TV unit mounted on the opposite south wall facing the bed'). "
        "Opening rule: when brief.wall_openings lists doors, windows, sliders, or glazing on a compass wall, preserve them on that wall in the image_prompt (approximate position along the wall) and let furniture defer to those openings.\n"
        "Pick concrete catalog SKUs that match each requested item type (e.g. for 'wardrobe' choose a catalog wardrobe; for 'bed' choose a catalog bed; for 'tv_unit' choose a catalog TV unit). If a requested item type has no matching catalog item, mention the gap in the rationale and select the closest substitute.\n"
        "Camera rule: when the assignment lists items on OPPOSING walls (north+south, or east+west), the image_prompt MUST describe a two-point/corner camera (e.g. 'wide-angle two-point perspective from the south-west corner looking toward the north-east, ~24mm equivalent') so BOTH opposing walls are visible in the rendered frame. Do not use a straight-on one-wall elevation when opposing walls are assigned. Mention the camera angle and which walls are visible in the image_prompt.\n"
        "Rationale rule: the rationale MUST start with a one-line 'Layout:' summary listing each wall and what is on it (e.g. 'Layout: North—bed + sconces; South—TV unit; East—accent wall; West—wardrobe.'). "
        "Then add a 'Compass placement:' section that names EVERY major catalog item with its compass wall (NORTH/SOUTH/EAST/WEST) so the user can verify against their wall picker.\n"
        "Image compass rule: every image_prompt MUST request a small compass-rose graphic in a corner (shape only, no N/S/E/W letters on the image). "
        "State which wall each hero item is on using NORTH/SOUTH/EAST/WEST in the prompt text and rationale, not as labels on the compass.\n"
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
            "If brief.wall_assignments has any non-empty arrays, every image_prompt MUST place those item types on the corresponding walls and the rationale MUST acknowledge the wall layout explicitly",
        ],
    }

    return _generate_json(
        cfg=cfg,
        system_text=system,
        user_json_payload=payload,
        context_images=context_images,
        schema=schema,
        temperature=0.5,
    )
