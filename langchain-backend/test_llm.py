import asyncio
import os
import sys

# Add the project root to sys.path
sys.path.append(os.getcwd())

import config
from routes.deep_analysis_v3 import _ask_llm_strategy_v3

async def test_llm():
    print("Testing LLM strategy call...")
    target_round = 1215
    top_5 = [1, 2, 3, 4, 5]
    exclude_10 = [40, 41, 42, 43, 44, 45, 39, 38, 37, 36]
    history_draws = [{"round": 1214, "numbers": [1, 10, 20, 30, 40, 45]}]
    combinations = [{"numbers": [1, 2, 3, 4, 5, 6]}]
    range_analysis = {"sum": {"range": [100, 180]}}
    
    result = await _ask_llm_strategy_v3(target_round, top_5, exclude_10, history_draws, combinations, range_analysis)
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(test_llm())
