import sys
import os

# 프로젝트 루트 경로를 시스템 경로에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.supabase_client import fetch_all_draws
from models.ensemble import LottoEnsemble

def run_auto_finetune():
    print("🚀 [MLOps] 자동 파인튜닝(증분 학습) 파이프라인 가동 시작...")
    
    draws = fetch_all_draws()
    if not draws:
        print("❌ [오류] DB에서 데이터를 불러오지 못했습니다.")
        return

    latest_round = draws[0]['round']
    print(f"📊 최신 {latest_round}회차까지 총 {len(draws)}개의 데이터를 확인했습니다.")
    print("🧠 7중 앙상블 모델에 최신 데이터를 주입하여 파인튜닝을 시작합니다...")
    
    # force_retrain=False: 기존 가중치(.pt)를 유지하고 새로운 패턴만 추가 학습
    ensemble = LottoEnsemble()
    result = ensemble.train_all(draws, force_retrain=False)
    
    if result.get("success"):
        print("✅ [MLOps] 파인튜닝 완료! 모든 모델의 뇌(.pt, .pkl, .json)가 업데이트되었습니다.")
    else:
        print(f"❌ [MLOps] 파인튜닝 실패: {result.get('message')}")

if __name__ == "__main__":
    run_auto_finetune()
