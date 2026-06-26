import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    
    # Optional: Max words per chunk when fallback chunking is used
    max_chunk_words: int = 2500

    class Config:
        env_file = ".env"

settings = Settings()
