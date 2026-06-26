from supabase import create_client, Client
from app.config import settings

def get_supabase_client() -> Client:
    """
    Initialize and return the Supabase client using the Service Role Key.
    The Service Role Key bypasses RLS and should only be used in secure backend environments.
    """
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise ValueError("Supabase URL and Service Role Key must be set in environment variables.")
        
    return create_client(settings.supabase_url, settings.supabase_service_role_key)

supabase = get_supabase_client()
