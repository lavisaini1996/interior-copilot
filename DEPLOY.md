# Deploy Interior Copilot

| Component | Platform | URL pattern |
|-----------|----------|-------------|
| Backend (FastAPI) | **Google Cloud Run** | `https://interior-copilot-api-xxxxx-uc.a.run.app` |
| Frontend (Vite + React) | **Vercel** | `https://your-app.vercel.app` |

Deploy the **backend first**, copy its URL, then set `VITE_API_BASE` on Vercel.

---

## Prerequisites

- [Google Cloud SDK (`gcloud`)](https://cloud.google.com/sdk/docs/install) logged in
- A GCP project with billing enabled
- [Vercel account](https://vercel.com) + Git repo connected (GitHub/GitLab)
- `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com/apikey)

---

## 1. Backend on Google Cloud Run

### One-time GCP setup

```powershell
gcloud auth login
gcloud config set project YOUR_GCP_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

### Deploy from repo root

From `g:\tilicho\interior-copilot` (where `Dockerfile` lives):

```powershell
cd g:\tilicho\interior-copilot

gcloud run deploy interior-copilot-api `
  --source . `
  --region us-central1 `
  --platform managed `
  --allow-unauthenticated `
  --timeout 300 `
  --memory 1Gi `
  --cpu 1 `
  --max-instances 10 `
  --set-env-vars "LLM_PROVIDER=gemini,CORS_ORIGINS=https://YOUR_VERCEL_APP.vercel.app"
```

Replace `YOUR_VERCEL_APP` with your real Vercel URL (add preview domains too if needed, comma-separated):

```text
CORS_ORIGINS=https://interior-copilot.vercel.app,https://interior-copilot-*.vercel.app
```

> Cloud Run does not support `*` wildcards in CORS. List each origin explicitly, or use `CORS_ORIGINS=*` only for testing.

### API key (recommended: Secret Manager)

```powershell
# Create secret once
echo -n "YOUR_GEMINI_API_KEY" | gcloud secrets create gemini-api-key --data-file=-

# Grant Cloud Run access
gcloud secrets add-iam-policy-binding gemini-api-key `
  --member="serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"

# Redeploy with secret
gcloud run deploy interior-copilot-api `
  --source . `
  --region us-central1 `
  --update-secrets GEMINI_API_KEY=gemini-api-key:latest
```

Or pass the key directly (simpler, less secure):

```powershell
--set-env-vars "GEMINI_API_KEY=your_key_here,LLM_PROVIDER=gemini,CORS_ORIGINS=https://your-app.vercel.app"
```

### Verify

```powershell
curl https://YOUR_SERVICE_URL/health
```

Expect: `{"status":"ok","llm_provider":"gemini"}`

### Optional env vars

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Required for Gemini |
| `LLM_PROVIDER` | `gemini` (default) or `openai` |
| `GEMINI_TEXT_MODEL` | e.g. `gemini-2.5-flash` |
| `GEMINI_IMAGE_MODEL` | Imagen model; leave empty to skip images |
| `CORS_ORIGINS` | Comma-separated Vercel URLs |
| `OPENAI_API_KEY` | If `LLM_PROVIDER=openai` |

### Local Docker test (optional)

```powershell
docker build -t interior-copilot-api .
docker run --rm -p 8080:8080 -e GEMINI_API_KEY=xxx -e PORT=8080 interior-copilot-api
```

---

## 2. Frontend on Vercel

### Import project

1. [vercel.com/new](https://vercel.com/new) → Import your Git repository.
2. **Root Directory**: set to `frontend` (not repo root).
3. Framework Preset: **Vite** (auto-detected).
4. Build Command: `npm run build` (default).
5. Output Directory: `dist` (default).

`frontend/vercel.json` already configures SPA rewrites.

### Environment variables (Vercel dashboard)

**Settings → Environment Variables** (Production + Preview):

| Name | Value |
|------|--------|
| `VITE_API_BASE` | `https://YOUR_CLOUD_RUN_URL` (no trailing slash) |

Redeploy after changing env vars (Vite bakes `VITE_*` at build time).

### Custom domain (optional)

Add domain in Vercel, then add that URL to Cloud Run `CORS_ORIGINS` and redeploy the API.

---

## 3. Wire them together

1. Deploy Cloud Run → copy service URL.
2. Set `VITE_API_BASE` on Vercel → **Redeploy** frontend.
3. Set `CORS_ORIGINS` on Cloud Run to your Vercel URL(s) → redeploy API if needed.
4. Open the Vercel app and test chat + generate.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| CORS error in browser | Add exact Vercel origin to `CORS_ORIGINS` on Cloud Run |
| `VITE_API_BASE` still localhost | Rebuild Vercel after setting env var |
| 503 / network errors | Cloud Run needs outbound internet for Gemini API |
| Request timeout | Increase Cloud Run `--timeout` (max 3600s); design gen can be slow |
| 400 on intake | Check Cloud Run logs: `gcloud run services logs read interior-copilot-api --region us-central1` |

---

## CI/CD (optional)

- **Cloud Run**: connect repo in Cloud Build or use `gcloud run deploy --source` on push.
- **Vercel**: auto-deploys on push to `main` when the repo is linked.
