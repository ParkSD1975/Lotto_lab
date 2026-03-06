import asyncio
import json
from supabase import create_client, Client
import os
from dotenv import load_dotenv

# .env 파일 로드 (config.py와 동일한 위치 가정)
load_dotenv('langchain-backend/.env')

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("Error: Missing SUPABASE_URL or SUPABASE_KEY")
    exit(1)

supabase: Client = create_client(url, key)

async def check_latest_analysis():
    print("Checking latest record in deep_analysis_history...")
    res = supabase.table("deep_analysis_history")\
        .select("*")\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()
    
    if not res.data:
        print("No analysis history found.")
        return

    record = res.data[0]
    print(f"ID: {record['id']}")
    print(f"Round: {record['target_round']}")
    print(f"Created At: {record['created_at']}")
    
    analysis_data = record.get("analysis_data")
    if isinstance(analysis_data, str):
        analysis_data = json.loads(analysis_data)
    
    strategy = analysis_data.get("strategy", {})
    filters = strategy.get("filter_recommendations", [])
    
    print(f"\nFilter Recommendations Count: {len(filters)}")
    for i, f in enumerate(filters):
        print(f"  {i+1}. {f.get('filter')}: {f.get('min', f.get('pattern', 'N/A'))}~{f.get('max', 'N/A')}")

if __name__ == "__main__":
    asyncio.run(check_latest_analysis())
