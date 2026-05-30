# DivyaDrishti — Streamlit Cloud Deployment Guide

## Prerequisites

1. **GitHub Account** — Your code must be in a public or private GitHub repo
2. **Streamlit Cloud Account** — Sign up at https://share.streamlit.io/
3. **Repository Setup** — Ensure your repo has:
   - `app.py` (main Streamlit app)
   - `requirements.txt` (dependencies)
   - `.streamlit/config.toml` (Streamlit configuration)
   - `tenders.db` or data source accessible to the app

## Deployment Steps

### Step 1: Prepare Your Repository

Make sure all files are committed to GitHub:

```bash
cd /Users/Dhrub/samastipur_tender_tracker
git add .
git commit -m "Deploy to Streamlit Cloud: add config and streamline setup"
git push origin main
```

### Step 2: Connect to Streamlit Cloud

1. Go to https://share.streamlit.io/
2. Click **Create app**
3. Select your GitHub repository
4. Choose the branch (typically `main`)
5. Set the main file path: `app.py`
6. Click **Deploy**

Streamlit Cloud will:
- Install dependencies from `requirements.txt`
- Run `streamlit run app.py`
- Deploy to a public URL (e.g., `https://YOUR-APP-NAME.streamlit.app/`)

### Step 3: Configure Secrets (if needed)

If your app needs API keys or sensitive config:

1. In Streamlit Cloud dashboard, go to **Settings** → **Secrets**
2. Add secrets in TOML format:

```toml
db_path = "tenders.db"
# api_key = "your-key"
```

Access them in `app.py`:

```python
import streamlit as st
db_path = st.secrets.get("db_path", "tenders.db")
```

### Step 4: Database & Data Handling

#### Option A: SQLite in Repository (Recommended for small DBs)
- Keep `tenders.db` in your repo
- Streamlit Cloud will include it automatically

#### Option B: Cloud Storage (for large DBs)
- Use AWS S3, Google Cloud Storage, or similar
- Download at startup in `app.py`:

```python
import boto3
s3 = boto3.client('s3')
s3.download_file('bucket-name', 'tenders.db', 'tenders.db')
```

#### Option C: Remote Database
- Use PostgreSQL, MySQL, or similar
- Store connection string in Secrets
- Query directly without storing a local DB file

### Step 5: Monitor & Troubleshoot

1. **View Logs**: Streamlit Cloud dashboard → **Settings** → **Logs**
2. **App Status**: Check if app is running or crashed
3. **Common Issues**:
   - Missing dependencies → Add to `requirements.txt`
   - Import errors → Check file paths
   - Memory issues → Reduce data or use caching

### Environment & Performance Tips

- Use `@st.cache_data` for expensive operations
- Set `maxUploadSize` in `.streamlit/config.toml`
- Use `st.spinner()` for long-running tasks
- Profile memory with `streamlit run app.py --logger.level=debug`

## Deployment Complete ✅

Your app should now be live at `https://YOUR-APP-NAME.streamlit.app/`

For updates, simply push new commits to your GitHub repo—Streamlit Cloud auto-deploys.

---

**Need Help?**
- Streamlit Docs: https://docs.streamlit.io/
- Streamlit Cloud Docs: https://docs.streamlit.io/streamlit-cloud/get-started
- GitHub Issues: Create an issue in your repo for debugging
