import os

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("DB_PATH", "./app.db")
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "./uploads")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Pinned deliberately rather than using the "gemini-flash-latest" alias. That alias
# tracks the newest flash model, whose free tier is capped at 20 requests PER DAY
# (verified against the live API: quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier,
# quotaValue 20) - low enough that a couple of document comparisons exhaust it and every
# subsequent change silently falls back to "unclassified". Quota is per-model, so pinning
# a stable model with a workable free tier keeps classification actually working.
# Override with the GEMINI_MODEL env var if you have billing enabled and want a newer model.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
