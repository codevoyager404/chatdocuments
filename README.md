# ChatDocuments

ChatDocuments is a document chat application that lets users upload PDF and PowerPoint files, build a searchable index, and ask grounded questions about the uploaded content.

## Stack

- Python / FastAPI backend
- FAISS-based vector index
- Cloudflare AI for embeddings and chat
- Static frontend with HTML, CSS, and vanilla JavaScript
- Railway for backend deployment
- Vercel for frontend deployment

## Local Development

Requirements:

- Python 3.11+
- `pip`

Setup:

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
```

Required environment variables:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `DATA_DIR=./data`

Open the app at:

- `http://localhost:8000`

## Deployment

### Backend on Railway

1. Deploy this project as a Python service.
2. Add a persistent volume mounted at `/data`.
3. Configure:
   - `CLOUDFLARE_API_TOKEN`
   - `CLOUDFLARE_ACCOUNT_ID`
   - `DATA_DIR=/data`
   - `ALLOWED_ORIGINS=https://your-frontend.vercel.app`
4. Railway starts the app from `Procfile` and uses `/ready` from `railway.json` for health checks.

If you skip the persistent volume, uploads, the FAISS index, and chat history will be lost on restart or redeploy.

### Frontend on Vercel

1. Deploy the repo as a static project.
2. Set:
   - `API_BASE_URL=https://your-backend.up.railway.app`
3. `vercel.json` builds the static frontend from `static/` and generates `config.js` with the backend URL.

### Recommended order

1. Deploy the backend on Railway.
2. Copy the Railway public URL.
3. Set that URL as `API_BASE_URL` on Vercel and redeploy.
4. Add the Vercel URL to `ALLOWED_ORIGINS` on Railway.
5. Redeploy Railway once more so the new CORS origin is loaded.

## Repository Layout

- `src/` - backend application code
- `static/` - frontend assets
- `.env.example` - local environment template
- `Procfile`, `railway.json` - Railway deployment settings
- `vercel.json` - Vercel build and runtime config
