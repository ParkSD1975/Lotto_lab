import asyncio
from db.repository import get_all_draws
from routes.deep_analysis_v3 import get_deep_analysis

async def test_deep_analysis():
    print("Testing get_deep_analysis()...")
    res = await get_deep_analysis()
    # It returns a JSONResponse, we can inspect its status code
    import json
    data = json.loads(res.body.decode('utf-8'))
    if data.get("success"):
        print("Success! Matrix data len:", len(data["analysis"]["matrix_data"]))
    else:
        print("Failed!", data)

if __name__ == "__main__":
    asyncio.run(test_deep_analysis())
