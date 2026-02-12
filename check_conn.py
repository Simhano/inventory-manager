import os
from supabase import create_client, Client

url = "https://pjnukijhtirbmdcjriqe.supabase.co"
key = "sb_publishable_qIH76fMi4gGpMKzp3sgERw_8_l9GAea"

def test_connection():
    print(f"Testing connection to {url}...")
    try:
        supabase: Client = create_client(url, key)
        # Try a simple select. Even if table doesn't exist, it checks auth.
        # If key is invalid, it usually fails format validation or returns 401.
        response = supabase.table("non_existent_table").select("*").execute()
        print("Response:", response)
    except Exception as e:
        print(f"Connection Failed: {e}")

if __name__ == "__main__":
    test_connection()
