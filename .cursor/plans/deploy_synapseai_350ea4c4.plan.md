---
name: Deploy SynapseAI
overview: Deploy the SynapseAI backend to Render (free Docker deployment) and frontend to Vercel (free Next.js hosting), then configure environment variables so they communicate correctly.
todos:
  - id: render-deploy
    content: Deploy backend on Render (Steps 1-6)
    status: completed
  - id: vercel-deploy
    content: Deploy frontend on Vercel (Steps 7-11)
    status: completed
  - id: cors-connect
    content: Add CORS_ORIGINS on Render with Vercel URL (Step 12)
    status: completed
  - id: test-e2e
    content: "Test full flow: landing page -> research -> report (Step 13)"
    status: completed
isProject: false
---

# Deploy SynapseAI to Render + Vercel

## Prerequisites (already done)

- GitHub repo: `https://github.com/tarunkauxhik/SynapseAI`
- Supabase project with schema applied
- API keys: Groq, Supabase, Tavily

---

## Part 1: Deploy Backend on Render

### Step 1 — Create a Render account

- Go to [render.com](https://render.com) and sign up using your GitHub account
- This automatically links your GitHub repos to Render

### Step 2 — Create a new Web Service

- From the Render dashboard, click **"New +"** (top right) then **"Web Service"**
- Select **"Build and deploy from a Git repository"**
- Connect your GitHub account if prompted
- Find and select **`tarunkauxhik/SynapseAI`**
- Click **Connect**

### Step 3 — Configure the service

Fill in these settings exactly:

- **Name**: `synapseai-backend`
- **Region**: Pick the closest to you (e.g., `Singapore` if you're in India)
- **Branch**: `main`
- **Root Directory**: leave **empty** (the Dockerfile is in the repo root)
- **Runtime**: select **"Docker"** (Render will auto-detect your `Dockerfile`)
- **Instance Type**: select **"Free"**

### Step 4 — Add environment variables

Click **"Add Environment Variable"** and add each of these one by one:

| Key | Value |
|-----|-------|
| `SUPABASE_URL` | Your Supabase project URL (from `.env`) |
| `SUPABASE_KEY` | Your Supabase anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | Your Supabase service role key |
| `GROQ_API_KEY` | Your Groq API key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` |
| `TAVILY_API_KEY` | Your Tavily API key |
| `DEBUG` | `False` |
| `MAX_RETRIES` | `3` |
| `RESEARCH_TIMEOUT` | `300` |

**Do NOT add `CORS_ORIGINS` yet** — you need the Vercel URL first. We'll come back to this.

### Step 5 — Deploy

- Click **"Create Web Service"**
- Render will build the Docker image and deploy it (takes 3-5 minutes)
- When done, you'll get a URL like: `https://synapseai-backend.onrender.com`
- **Copy this URL** — you need it for the frontend

### Step 6 — Verify backend is running

- Open `https://synapseai-backend.onrender.com/health` in your browser
- You should see: `{"status": "healthy", "timestamp": "..."}`
- Also check `https://synapseai-backend.onrender.com/docs` for the Swagger API docs

**Important note about Render free tier**: The server spins down after 15 minutes of inactivity. First request after sleep takes ~30-60 seconds to cold start. This is normal.

---

## Part 2: Deploy Frontend on Vercel

### Step 7 — Create a Vercel account

- Go to [vercel.com](https://vercel.com) and sign up using your GitHub account

### Step 8 — Import the project

- From the Vercel dashboard, click **"Add New..."** then **"Project"**
- Find and select **`tarunkauxhik/SynapseAI`**
- Click **Import**

### Step 9 — Configure the project

- **Framework Preset**: Vercel should auto-detect **"Next.js"**
- **Root Directory**: Click **"Edit"** and set it to **`frontend`** (this is critical — the Next.js app is inside the `frontend/` folder, not the repo root)
- **Build Command**: leave default (`npm run build`)
- **Install Command**: leave default (`npm install`)

### Step 10 — Add environment variables

Click **"Environment Variables"** and add:

| Key | Value |
|-----|-------|
| `NEXT_PUBLIC_API_URL` | `https://synapseai-backend.onrender.com` (your Render URL from Step 5, **no trailing slash**) |

This is the only env var the frontend needs. It tells the frontend where the backend lives. This works because of [frontend/src/lib/api.ts](frontend/src/lib/api.ts) line 4:
```
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
```

### Step 11 — Deploy

- Click **"Deploy"**
- Vercel builds and deploys in ~1-2 minutes
- You'll get a URL like: `https://synapse-ai.vercel.app`
- **Copy this URL**

---

## Part 3: Connect Frontend and Backend (CORS)

Right now the frontend can try to call the backend, but the backend will **reject** the requests because of CORS (Cross-Origin Resource Sharing). You need to tell the backend to allow requests from your Vercel URL.

### Step 12 — Add CORS_ORIGINS on Render

- Go to your Render dashboard: [dashboard.render.com](https://dashboard.render.com)
- Click on your **`synapseai-backend`** service
- Go to **"Environment"** tab
- Click **"Add Environment Variable"**
- Key: `CORS_ORIGINS`
- Value: `https://synapse-ai.vercel.app` (your actual Vercel URL, **no trailing slash**)
  - If you want to allow multiple origins: `https://synapse-ai.vercel.app,http://localhost:3000`
- Click **"Save Changes"**
- Render will automatically redeploy with the new variable

This works because of [app/api/routes.py](app/api/routes.py) line 55:
```python
allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
```

---

## Part 4: Test Everything

### Step 13 — End-to-end test

1. Open your Vercel URL (e.g., `https://synapse-ai.vercel.app`)
2. You should see the SynapseAI landing page
3. Type a topic like **"Quantum Computing"** and click Start
4. Wait for Render to wake up (up to 60s on free tier first hit)
5. The page should redirect to the research results page and show progress
6. Wait for the report to generate (1-2 minutes)

### Troubleshooting checklist if it doesn't work

- **Page loads but "Failed to start research" error**: CORS issue. Check that `CORS_ORIGINS` on Render matches your exact Vercel URL (with `https://`, no trailing slash)
- **Page loads but hangs forever after clicking Start**: Backend is cold starting on Render. Wait 60s, try again. Check `https://your-render-url.onrender.com/health` first
- **Backend health check fails**: Check Render logs (Dashboard > your service > Logs) for Python errors. Likely a missing env var
- **"Internal Server Error" from backend**: Check Render logs. Usually means a Supabase or Groq API key is wrong

---

## Summary of what goes where

```
GitHub Repo (tarunkauxhik/SynapseAI)
    |
    |--- Render reads Dockerfile, builds backend
    |       URL: https://synapseai-backend.onrender.com
    |       Env vars: SUPABASE_URL, SUPABASE_KEY, GROQ_API_KEY, CORS_ORIGINS, etc.
    |
    |--- Vercel reads frontend/ folder, builds Next.js
            URL: https://synapse-ai.vercel.app
            Env vars: NEXT_PUBLIC_API_URL (points to Render URL)
```

No code changes are needed. All configuration is done through environment variables on the deployment platforms.
