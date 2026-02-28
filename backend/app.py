"""
DIY Safety Analyzer — Python Backend (FastAPI)

Uses GROQ_API_KEY and SUPABASE_URL directly from .env.
No user-facing API key management — the key is configured server-side.

Pipeline:
  1. YouTube transcript fetching
  2. Groq LLM streaming step extraction (with DIY detection + safety category classification)
  3. Step embedding via sentence-transformers (all-MiniLM-L6-v2, 384-dim)
  4. pgvector cosine-similarity search against safety_rules table
  5. Final Groq LLM safety assessment
  6. In-memory analysis cache (24h TTL, max 200 entries)
"""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import router
from cache import AnalysisCache

load_dotenv()

# Shared state
cache = AnalysisCache()

# Environment config — all from .env
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL", "")
MODEL = os.getenv("MODEL", "qwen/qwen3-32b")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not GROQ_API_KEY:
        print("WARNING: GROQ_API_KEY not set in .env — analysis will fail.")
    if not DATABASE_URL:
        print("WARNING: DATABASE_URL / SUPABASE_URL not set — rule matching will fail.")
    print(f"Model: {MODEL}")
    print(f"API Key: {'configured' if GROQ_API_KEY else 'MISSING'}")
    print(f"Database: {'configured' if DATABASE_URL else 'MISSING'}")
    yield


app = FastAPI(title="DIY Safety Analyzer API", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
