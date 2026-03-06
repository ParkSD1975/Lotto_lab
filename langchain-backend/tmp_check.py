import sys
import json
import traceback

sys.path.append(r'c:\Users\psdet\Desktop\로또개발\langchain-backend')

try:
    from db.repository import get_client
    client = get_client()
    res = client.table("deep_analysis_history").select("analysis_data, id").order("created_at", desc=True).limit(1).execute()
    history_id = res.data[0]["id"]
    data = res.data[0]["analysis_data"]
    if isinstance(data, str): data = json.loads(data)
    
    customs = data.get("analysis", {}).get("custom_evaluations", [])
    
    print(f"History ID: {history_id}, Found {len(customs)} custom evals")
    if customs:
        print(json.dumps(customs[0], ensure_ascii=False, indent=2))
        
except Exception as e:
    traceback.print_exc()
