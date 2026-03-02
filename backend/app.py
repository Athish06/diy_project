"""
DIY Safety Analyzer — Python Backend (FastAPI)

Pipeline:
  1. YouTube transcript fetching
  2. Groq LLM streaming step extraction (DIY detection + safety categories)
  3. Step embedding via sentence-transformers (all-MiniLM-L6-v2, 384-dim)
  4. pgvector cosine-similarity search against safety_rules table
  5. Multi-model LLM safety assessment (parallel)
  6. In-memory analysis cache (24h TTL, max 200 entries)
"""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from api.routes import router, ws_router
from core.config import get_api_key, get_model, get_database_url


@asynccontextmanager
async def lifespan(app: FastAPI):
    api_key = get_api_key()
    db_url = get_database_url()
    model = get_model()
    if not api_key:
        print("WARNING: GROQ_API_KEY not set in .env — analysis will fail.")
    if not db_url:
        print("WARNING: DATABASE_URL / SUPABASE_URL not set — rule matching will fail.")
    print(f"Model: {model}")
    print(f"API Key: {'configured' if api_key else 'MISSING'}")
    print(f"Database: {'configured' if db_url else 'MISSING'}")
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
app.include_router(ws_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
