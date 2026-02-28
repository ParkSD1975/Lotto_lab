import sys
import json
import asyncio
from routes.deep_analysis_v3 import get_deep_analysis

async def main():
    print("Testing get_deep_analysis()...")
    try:
        # Get analysis without returning JSON response wrapper
        response = await get_deep_analysis(None)
        
        # We need the inner dict if it returns a JSONResponse
        if hasattr(response, 'body'):
            data = json.loads(response.body.decode('utf-8'))
        else:
            data = response
            
        if not data.get("success"):
            print("Failed.")
            return
            
        custom = data.get("analysis", {}).get("custom_evaluations", [])
        print(f"Got {len(custom)} custom evaluations")
        
        for c in custom[:3]:
            print(f"\nTitle: {c.get('title')}")
            scores = c.get("model_scores", {})
            for m in ["lstm", "xgboost", "cnn", "transformer", "markov", "autoencoder", "gnn"]:
                sd = scores.get(m, {})
                print(f"  {m}: score={sd.get('score')} reason={sd.get('reasoning')}")
                
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
