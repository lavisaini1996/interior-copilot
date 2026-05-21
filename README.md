# Interior Copilot – Moodboard Intake (React + FastAPI + Gemini)

This is a minimal UI that:

- Collects user input via multi-turn Q&A until the “design brief” is complete
- Uses Google Gemini (text) to structure the brief + create 2–3 image prompts
- Uses Imagen via the Gemini API to generate moodboard and design images

## Setup

1) Create a virtual environment (recommended), then install deps:

```bash
pip install -r requirements.txt
```

2) Configure your API key:

- Copy `.env.example` to `.env`
- Default provider is **Gemini** (`LLM_PROVIDER=gemini`). Set `GEMINI_API_KEY=...` from [Google AI Studio](https://aistudio.google.com/apikey).
- To switch to **OpenAI** for testing, in `.env` set:

  ```bash
  LLM_PROVIDER=openai
  OPENAI_API_KEY=sk-...
  # OPENAI_TEXT_MODEL=gpt-4.1-mini
  # OPENAI_IMAGE_MODEL=gpt-image-1
  ```

  Restart the backend; `GET /health` returns the active provider.

## Run (React UI + FastAPI)

1) Backend:

```bash
cd g:\tilicho\interior-copilot
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --reload --port 8000
```

2) Frontend:

```bash
cd g:\tilicho\interior-copilot\frontend
npm install
npm run dev
```

If your backend isn’t on `http://localhost:8000`, create `frontend/.env`:

```bash
VITE_API_BASE=http://localhost:8000
```

## Deploy (GCP + Vercel)

- **Backend**: Google Cloud Run — see [DEPLOY.md](./DEPLOY.md)
- **Frontend**: Vercel (root directory: `frontend`, env: `VITE_API_BASE`)

## Notes

- **Imagen** (the default `GEMINI_IMAGE_MODEL`) is often limited to **paid** Google AI / Cloud billing. On a free key you may see errors like “Imagen … only available on paid plans”; the app still returns **catalog designs and pricing**, but preview images may be empty. Set `GEMINI_IMAGE_MODEL=` (empty) to avoid calling Imagen at all.
- If image generation fails for other reasons (quota, overload), Q&A and design planning still run.

