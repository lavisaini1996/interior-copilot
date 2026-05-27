"""
Provider dispatcher for the LLM backend.

Selects between Gemini (default) and OpenAI based on the LLM_PROVIDER env var
(values: "gemini" or "openai"). Resolution is lazy so this module is safe to
import before load_dotenv() runs.

Public surface mirrors the per-provider client modules:
  - env_config()
  - extract_rooms_from_floorplan(...)
  - extract_room_dimensions_from_floorplan(...)
  - extract_plan_north_from_floorplan(...)
  - extract_wall_openings_from_floorplan(...)
  - generate_next_questions(...)
  - generate_moodboard_prompts(...)
  - generate_catalog_designs(...)
  - generate_images(...)
"""

from __future__ import annotations

import logging
import os
from types import ModuleType
from typing import Any

logger = logging.getLogger("interior_copilot.llm")

_VALID_PROVIDERS = {"gemini", "openai"}
_cached_module: ModuleType | None = None
_cached_provider: str | None = None


def active_provider() -> str:
    raw = (os.environ.get("LLM_PROVIDER") or "gemini").strip().lower()
    return raw if raw in _VALID_PROVIDERS else "gemini"


def _resolve() -> ModuleType:
    global _cached_module, _cached_provider
    provider = active_provider()
    if _cached_module is not None and _cached_provider == provider:
        return _cached_module

    if provider == "openai":
        from backend import openai_client as mod
    else:
        from backend import gemini_client as mod

    _cached_module = mod
    _cached_provider = provider
    logger.info("LLM provider resolved: %s", provider)
    return mod


def env_config() -> Any:
    return _resolve().env_config()


def extract_rooms_from_floorplan(**kwargs: Any) -> Any:
    return _resolve().extract_rooms_from_floorplan(**kwargs)


def extract_room_dimensions_from_floorplan(**kwargs: Any) -> Any:
    return _resolve().extract_room_dimensions_from_floorplan(**kwargs)


def extract_plan_north_from_floorplan(**kwargs: Any) -> Any:
    return _resolve().extract_plan_north_from_floorplan(**kwargs)


def extract_wall_openings_from_floorplan(**kwargs: Any) -> Any:
    return _resolve().extract_wall_openings_from_floorplan(**kwargs)


def generate_next_questions(**kwargs: Any) -> Any:
    return _resolve().generate_next_questions(**kwargs)


def generate_moodboard_prompts(**kwargs: Any) -> Any:
    return _resolve().generate_moodboard_prompts(**kwargs)


def generate_catalog_designs(**kwargs: Any) -> Any:
    return _resolve().generate_catalog_designs(**kwargs)


def generate_images(**kwargs: Any) -> Any:
    return _resolve().generate_images(**kwargs)
