# Deployment Guide — SLO County Election Dashboard (v2)

## Overview

v2 is built for [Vercel](https://vercel.com) using a Python serverless function.  
No database, no build step, no dependencies beyond the Python standard library.

```
v2/
├── api/
│   └── results.py       # Serverless function — fetches & parses XML
├── public/
│   └── index.html       # Dashboard UI (static, served by Vercel CDN)
├── vercel.json          # Vercel configuration
├── requirements.txt     # Empty — stdlib only
└── DEPLOY.md            # This file
```

---

## Prerequisites

- [Git](https://git-scm.com) installed
- [GitHub](https://github.com) account (free)
- [Vercel](https://vercel.com) account (free) — sign up with your GitHub account
- [Vercel CLI](https://vercel.com/docs/cli) (optional, for local testing)

---

## Step 1 — Push to GitHub

### If this is a new repo

```bash
# From inside the v2/ folder (or the root of this project)
git init
git add .
git commit -m "Initial commit — v2 Vercel deployment"
```

Then create a new repo on GitHub (github.com → New repository).  
**Do not** initialize it with a README — you'll push your local code.

```bash
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git branch -M main
git push -u origin main
```

### If you already have a GitHub repo

```bash
git add .
git commit -m "Add v2 Vercel deployment"
git push
```

---

## Step 2 — Connect to Vercel

1. Go to [vercel.com/new](https://vercel.com/new)
2. Click **"Import Git Repository"**
3. Authorize Vercel to access your GitHub account if prompted
4. Select your repo from the list
5. **Configure the project:**
   - **Framework Preset:** Other (leave blank)
   - **Root Directory:** `v2` ← important if your repo contains both v1 and v2
   - Leave Build Command and Output Directory blank
6. Click **Deploy**

Vercel will build and deploy. In ~30 seconds you'll have a live URL like  
`https://your-project-name.vercel.app`

---

## Step 3 — Add a Custom Domain (optional)

1. In your Vercel project dashboard → **Settings → Domains**
2. Click **Add Domain** and enter your domain (e.g. `election.yourname.dev`)
3. Vercel will show you DNS records to add — log in to your domain registrar
   (Namecheap, Cloudflare, etc.) and add them
4. Wait a few minutes for DNS to propagate — Vercel will automatically
   provision an SSL certificate

---

## How it works after deployment

| Event | What happens |
|---|---|
| Visitor loads the page | Browser fetches `index.html` from Vercel's CDN (fast, cached) |
| Page loads | JS calls `GET /api/results` |
| `/api/results` (first call or cache stale) | Python function fetches XML from SLO County, parses it, returns JSON. Result is cached in memory for 1 hour. |
| `/api/results` (cache warm) | Returns cached JSON immediately — no upstream request |
| Every hour | Browser auto-calls `GET /api/results` again |

**Rate to SLO County:** At most once per hour per warm Lambda instance.  
Vercel may run multiple instances across regions, but traffic to a personal  
dashboard won't cause meaningful load on the county server.

---

## Updating the dashboard

Any push to your `main` branch on GitHub will trigger an automatic  
re-deployment on Vercel — no manual steps needed.

```bash
# Make your changes, then:
git add .
git commit -m "Describe your change"
git push
```

Vercel will deploy in ~30 seconds and the new version goes live automatically.

---

## Local development (optional)

Install the Vercel CLI to run v2 locally before pushing:

```bash
npm i -g vercel
cd v2/
vercel dev
```

This spins up a local server at `http://localhost:3000` that mimics the  
Vercel serverless environment — useful for testing the API function.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `404` on `/api/results` | Check that `vercel.json` is present and `Root Directory` is set to `v2` in Vercel settings |
| Stale data after an hour | Check the Vercel function logs (Dashboard → Functions → results.py) for errors fetching from SLO County |
| SLO County URL changes | Update `RESULTS_URL` at the top of `api/results.py` and push |
| Function timeout | Increase `maxDuration` in `vercel.json` (max 10s on free tier, 300s on Pro) |
| CORS errors | The `Access-Control-Allow-Origin: *` header is already set in `results.py` |

---

## Free tier limits (Vercel Hobby plan)

| Resource | Limit | Expected usage |
|---|---|---|
| Bandwidth | 100 GB/mo | ~negligible for a text dashboard |
| Function invocations | 100,000/mo | ~744 (once/hour, one instance) |
| Function duration | 10s max | XML fetch + parse takes ~2–3s |
| Deployments | Unlimited | ✓ |

You will not hit these limits with normal personal use.

---

## Attribution & disclaimer

Per best practices and SLO County data use, the dashboard displays:  
- Source credit: *San Luis Obispo County Clerk-Recorder*  
- Results status from the XML (e.g. "UNOFFICIAL ELECTION RESULTS")

These are pulled directly from the data and displayed automatically.
