import sys
import json
import logging
from routes.deep_analysis_v3 import fetch_all_draws
from models.ensemble import LottoEnsemble

def main():
    print("Testing Ensemble")
    
    # 1. Fetch some recent draws
    draws = fetch_all_draws()
    recent = sorted(draws, key=lambda d: d['round'])[-200:]
    
    ensemble = LottoEnsemble()
    prediction = ensemble.predict(recent)
    
    contribs = prediction.get("model_contributions", {})
    
    print("\n--- MODEL CONTRIBUTIONS SUMMARY ---")
    models = ["lstm", "xgboost", "cnn", "transformer", "markov", "autoencoder", "gnn"]
    for m in models:
        c = contribs.get(m, {})
        print(f"{m}: len={len(c)}")
        if c:
            vals = list(c.values())
            print(f"  Max: {max(vals):.4f}, Min: {min(vals):.4f}, Avg: {sum(vals)/len(vals):.4f}")
            print(f"  First 5 items: {list(c.items())[:5]}")
            
    # Mocking target numbers
    test_nums = [3, 11, 20, 31, 40]
    print(f"\n--- Testing logic with {test_nums} ---")
    
    for m in models:
        m_contrib = contribs.get(m, {})
        if not m_contrib:
            print(f"{m} score = 0 (No data)")
            continue
            
        all_vals = sorted(m_contrib.values(), reverse=True)
        total_cnt = len(all_vals)
        val_range = (all_vals[0] - all_vals[-1]) if all_vals else 0
        if val_range < 1e-9:
            print(f"{m} score = 50 (Uniform dist) Range={val_range}")
            continue
            
        m_scores_for_nums = []
        for n in test_nums:
            v = m_contrib.get(n, 0)
            higher_cnt = sum(1 for x in all_vals if x > v)
            percentile = min((total_cnt - higher_cnt) / max(total_cnt, 1) * 100, 95)
            m_scores_for_nums.append(percentile)
            
        m_avg = sum(m_scores_for_nums) / len(m_scores_for_nums) if m_scores_for_nums else 0
        avg_prob = sum(m_contrib.get(n, 0) for n in test_nums) / len(test_nums) if test_nums else 0
        baseline = sum(m_contrib.values()) / max(len(m_contrib), 1)
        
        final_score = m_avg
        if avg_prob < baseline * 0.5:
            final_score *= 0.5
            
        score = int(max(0, min(100, final_score)))
        
        print(f"{m} score = {score} (m_avg={m_avg:.1f}, prob={avg_prob:.4f}, baseline={baseline:.4f})")

if __name__ == '__main__':
    main()
