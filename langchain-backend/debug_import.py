
try:
    from models.ensemble import LottoEnsemble
    print("[OK] models.ensemble imported successfully.")
except Exception as e:
    import traceback
    print(f"[FAIL] models.ensemble import failed: {e}")
    traceback.print_exc()

try:
    from chains.analysis_chain import analyze_lotto
    print("[OK] chains.analysis_chain imported successfully.")
except Exception as e:
    import traceback
    print(f"[FAIL] chains.analysis_chain import failed: {e}")
    traceback.print_exc()
