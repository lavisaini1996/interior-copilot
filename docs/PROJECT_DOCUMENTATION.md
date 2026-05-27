# Interior Copilot — Project Documentation

> **Purpose of this document:** Structured technical + product write-up for portfolio, blog, or interview prep.  
> **Source of truth:** Implemented code in this repository and deployment steps performed in this project.  
> **Note:** Business metrics, client names, and team size are **not** stated below unless you add them in the “Open items” section.

---

## 1. Project overview

**Interior Copilot** is a web application that helps users design a room from a floor plan and preferences. It:

- Collects requirements through a **guided multi-step workflow** and **chat-based intake**
- Reads **floor plan images** (rooms, dimensions, doors/windows per wall)
- Lets users assign **furniture and fixtures to compass walls** (North / South / East / West)
- Generates **catalog-constrained design options** with **INR pricing** and optional **rendered preview images**

**Stack (as implemented):**

| Layer | Technology |
|--------|------------|
| Frontend | React 18, TypeScript, Vite |
| Backend | Python, FastAPI, Uvicorn |
| LLM (default) | Google Gemini API (`google-genai` SDK) |
| LLM (optional) | OpenAI API (`LLM_PROVIDER=openai`) |
| Image generation (default) | Google **Imagen** via Gemini API (`generate_images`) |
| Catalog | Static JSON (`backend/catalog.json`) |
| Production deploy | Backend: **Google Cloud Run** · Frontend: **Vercel** |

---

## 2. Product / business problems addressed

*(Describe in your own words for a blog; suggested framing based on features built.)*

| Problem area | How the app addresses it |
|--------------|---------------------------|
| Scattered intake | Single linear workflow: design type → floor plan → plan setup → wall layout → style/budget → generate |
| Floor plan interpretation | Vision LLM extracts rooms, dimensions, and openings instead of manual re-entry only |
| Orientation confusion | User sets **plan north** (degrees clockwise from image top); doors/windows and furniture use the same N/S/E/W frame |
| Catalog vs fantasy designs | Designs must use SKUs from `catalog.json`; prices and materials are computed in INR |
| Placement trust | Wall picker + server/client **space checks** + **placement summary** and compass cues in rationale and image prompts |

**Open items for you to fill in:**

- Who was the client or internal stakeholder?
- What happened before this tool existed (spreadsheets, manual renders, etc.)?
- Any measured outcomes (time saved, fewer revision rounds)?

---

## 3. System architecture (high level)

```text
[Browser - Vercel]
   React UI (workflow, wall layout, chat)
        |  HTTPS  (VITE_API_BASE → Cloud Run URL)
        v
[FastAPI on Cloud Run]
   /api/intake      → brief + questions (Gemini JSON)
   /api/designs     → catalog designs + Imagen images
   /api/moodboard   → moodboard prompts + images
   /health
        |
        v
[Google Gemini API]
   Text: gemini-2.5-flash (+ fallback gemini-2.0-flash)
   Images: imagen-4.0-generate-001 (optional; may be empty on free tier)
```

**Provider switch:** `LLM_PROVIDER` env var (`gemini` | `openai`) routes all LLM calls through `backend/llm.py` to the correct client module.

---

## 4. Models and configuration

### Default (Gemini) — from `.env.example` and `gemini_client.py`

| Role | Env variable | Default model |
|------|----------------|---------------|
| Text / vision / JSON | `GEMINI_TEXT_MODEL` | `gemini-2.5-flash` |
| Text fallback (503, etc.) | `GEMINI_TEXT_MODEL_FALLBACK` | `gemini-2.0-flash` |
| Image generation | `GEMINI_IMAGE_MODEL` | `imagen-4.0-generate-001` |

- Text calls use **`generate_content`** with **`response_mime_type: application/json`** and a **JSON schema** per task (structured outputs).
- Image calls use **`generate_images`** with PNG output.
- If `GEMINI_IMAGE_MODEL` is empty, image generation is skipped (designs still return without previews).
- Imagen failures on free/paid-plan limits are caught; the API **degrades gracefully** (no image bytes, rest of design intact).

### Optional OpenAI path

Same logical functions exist in `backend/openai_client.py` when `LLM_PROVIDER=openai`.

---

## 5. End-to-end flow (how it works)

### 5.1 Frontend linear workflow

Eight steps (`frontend/src/ui/workflow.tsx`):

1. **Design type** — room/module + material preference  
2. **Floor plan** — image upload and/or text description  
3. **Plan setup** — north rotation (compass overlay), room picker if multiple rooms detected  
4. **Wall layout** — place catalog item types on N/S/E/W (or skip)  
5. **Style & budget** — chat until brief is complete  
6. **Style references** — optional images  
7. **Generate** — calls `/api/designs`  
8. **Results** — options with rationale, placement map, catalog lines, optional PNG  

Step unlock rules are **derived from brief state** (not a manual step counter).

### 5.2 Intake (`POST /api/intake`)

When the user sends chat or updates the brief:

1. **Merge** client brief with server defaults (`backend/main.py`).
2. If **floor plan images** are present:
   - **`extract_rooms_from_floorplan`** — list rooms (and dimensions when visible).
   - **`extract_room_dimensions_from_floorplan`** — if length/width not already set.
   - **`extract_wall_openings_from_floorplan`** — doors/windows per wall for selected room, using **north angle** from brief.
   - Failures on openings are **logged and ignored**; intake continues with empty openings.
3. **`generate_next_questions`** — returns updated brief, follow-up questions, `is_complete`.
4. Server **gates** completion (e.g. style direction, budget band in INR).

Floor plan images are sent as **base64** in JSON (`mime_type` + `data_base64`).

### 5.3 Design generation (`POST /api/designs`)

1. **`generate_catalog_designs`** (Gemini + catalog payload):
   - Picks **catalog item IDs** and **material quantities** from room size and budget band.
   - Builds **`image_prompt`** and **`rationale`** per option (wall layout, openings, camera angle for opposing walls).
2. Server may **inject** extra chat messages: wall layout text, detected openings, placement verification map.
3. For each design:
   - Resolve catalog items and material line totals (INR).
   - **`enhance_image_prompt_for_compass`** — append compass-rose instruction (shape only, no N/S/E/W on image).
   - Append **`format_placement_verification`** to rationale / `placement_summary`.
   - **`generate_images`** — one PNG per option from `image_prompt` (if Imagen configured).
4. Response: designs with `image_base64_png`, `estimated_total`, etc.

### 5.4 Moodboard (`POST /api/moodboard`)

- **`generate_moodboard_prompts`** → short list of prompts from brief.  
- **`generate_images`** per prompt (same Imagen path).

---

## 6. How floor plan “scanning” works (vision, not classical CV)

There is **no separate OCR or CV pipeline** in-repo. Scanning is done by **multimodal Gemini** calls:

| Function | Input | Output | Temperature |
|----------|--------|--------|-------------|
| `extract_rooms_from_floorplan` | Floor plan image(s) | `rooms_detected` list | 0.1 |
| `extract_room_dimensions_from_floorplan` | Floor plan image(s) | `room_length_m`, `room_width_m`, etc. | 0.1 |
| `extract_wall_openings_from_floorplan` | Image(s) + target room + **north degrees** | `wall_openings` per N/S/E/W | 0.1 |

**Images are attached** to the model request as binary parts (`_parts_from_system_payload_and_images` in `gemini_client.py`).

**Compass / north rule for openings:**

- User sets `floorplan_north_clockwise_deg` (0° = top of image is north).
- System prompt tells the model to assign each door/window to **one** of north/south/east/west using that rotation.
- Prompt explicitly says: do not invent openings; use empty arrays if none visible.

**Room targeting:**

- Openings run when a **room is selected** (`selected_room_id` / `selected_room_name`).

---

## 7. Wall layout, validation, and compass in outputs

### 7.1 User wall assignments

- Stored in brief as `wall_assignments: { north: [], south: [], east: [], west: [] }` (item type strings).
- Frontend **Wall layout** UI; optional skip.

### 7.2 Space validation (`backend/wall_placement.py` + `frontend/src/ui/wallPlacement.ts`)

- Heuristic **metres per item type** along a wall (`ITEM_WALL_SPACE_M`).
- Subtracts **opening descriptions** (parsed for width hints) from available wall length.
- **`can_place_on_wall`** — blocks UI placement when insufficient space; API uses same rules for messaging consistency.

### 7.3 Placement verification & images

- **`format_placement_verification`** — text map: plan north angle, per-wall furniture + openings, room size.
- Shown in UI as **`placement_summary`** on each design card.
- Image prompts request a **compass-rose graphic without cardinal letters**; **NORTH/SOUTH/EAST/WEST** appear in **text** (rationale / prompt), not on the rose.

---

## 8. Image generation (detailed)

### 8.1 What produces the prompt?

1. **Catalog design step** (`generate_catalog_designs`) writes a detailed **`image_prompt`** per option:
   - Room dimensions in metres (when known)
   - Catalog-backed furniture on assigned walls
   - Doors/windows from `wall_openings`
   - Camera rule for opposing walls (corner / two-point perspective)
   - Style/material/budget constraints from brief
2. **`enhance_image_prompt_for_compass`** may append compass placement cues.

### 8.2 What renders the image?

```python
# gemini_client.generate_images
client.models.generate_images(
    model=cfg.image_model,  # default imagen-4.0-generate-001
    prompt=prompt,
    config=GenerateImagesConfig(number_of_images=n, output_mime_type="image/png"),
)
```

- Retries on transient errors (`_with_retries`).
- Expected failures (e.g. Imagen not on plan) → **empty image list**, design still returned.

### 8.3 What the user sees

- Base64 PNG in API response → displayed and downloadable in the React UI.
- If generation skipped: “No image returned for this option” with full rationale and pricing still present.

---

## 9. Reliability and errors

| Area | Behavior |
|------|----------|
| Gemini 503 / rate limits | Retry with backoff; fallback text model |
| Network/DNS to Google | Classified as network error; HTTP 503 message to client (`backend/http_errors.py`) |
| Opening extraction fails | Warning log; empty openings; intake continues |
| Imagen unavailable | Warning log; designs without images |
| CORS | `CORS_ORIGINS` env (comma-separated); `*` allowed for testing |

---

## 10. Deployment (as configured in this project)

| Component | Platform | Notes |
|-----------|----------|--------|
| API | Google Cloud Run | Dockerfile, port 8080, 300s timeout, 1Gi memory |
| UI | Vercel | Root directory `frontend`; **`VITE_API_BASE`** required at build time |
| Secrets | Env vars on Cloud Run | `GEMINI_API_KEY`, etc. (Secret Manager recommended) |

Example production API base:

`https://interior-copilot-api-576475670917.us-central1.run.app`

Frontend production example:

`https://interior-copilot.vercel.app`

See [DEPLOY.md](../DEPLOY.md) for commands.

---

## 11. API surface (reference)

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Status + active LLM provider |
| `POST /api/intake` | Update brief, floor plan vision passes, follow-up questions |
| `POST /api/designs` | Catalog designs + optional Imagen renders |
| `POST /api/moodboard` | Moodboard prompts + images |

---

## 12. Key files (for readers of the codebase)

| Path | Responsibility |
|------|----------------|
| `frontend/src/ui/App.tsx` | Main UI, workflow, wall layout, generate |
| `frontend/src/ui/workflow.tsx` | Step definitions and unlock logic |
| `frontend/src/ui/wallPlacement.ts` | Client-side wall space checks |
| `frontend/src/ui/api.ts` | API client (`VITE_API_BASE`) |
| `backend/main.py` | FastAPI routes, intake pipeline, design assembly |
| `backend/gemini_client.py` | Gemini text/vision JSON + Imagen |
| `backend/llm.py` | Provider dispatcher |
| `backend/wall_placement.py` | Placement map, compass prompt helper, wall math |
| `backend/catalog.json` | SKUs, materials, INR prices |

---

## 13. Open items (complete for your blog / interview)

Use this checklist so the doc stays honest (per your documentation prompt):

1. **Client / business goal** — Who commissioned this and what decision does the output support?  
2. **Before vs after** — What was manual or broken before Interior Copilot?  
3. **Your role** — Which parts did you personally build (UI, API, prompts, deploy)?  
4. **Metrics** — Any real numbers (latency, cost per design, user count)?  
5. **Imagen in production** — Paid Google AI plan or text-only in prod?  
6. **Lessons learned** — Biggest prompt or infra surprises?

---

## 14. One-paragraph elevator pitch (draft)

Interior Copilot turns a floor plan and a short conversation into **measured, catalog-priced room design options** for the Indian market (INR). Gemini reads the plan for **rooms, dimensions, and doors/windows by wall**, aligned to a user-controlled **north** direction. Users place furniture on **N/S/E/W** walls with instant **space validation**, then the system plans **three distinct catalog-backed options** and optionally renders them with **Imagen**, while **compass placement** is spelled out in text so layouts can be verified against the plan.

---

*Last updated from repository state. Edit section 13 with your real business context before publishing externally.*
