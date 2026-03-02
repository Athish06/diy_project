"""Centralized environment configuration."""

import os


def get_api_key() -> str:
    """Get the Groq API key from environment."""
    return os.getenv("GROQ_API_KEY", "")


def get_model() -> str:
    """Get the default LLM model name from environment."""
    return os.getenv("MODEL", "qwen/qwen3-32b")


def get_database_url() -> str:
    """Get the database connection URL from environment."""
    return os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL", "")
