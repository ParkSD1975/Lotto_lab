import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import main
    print("Successfully imported main module. Server startup check passed.")
    
    # Verify logical correctness: helper function should exist but model not loaded yet
    from chains.analysis_chain import get_ensemble, ensemble
    if ensemble is None:
        print("[OK] Lazy loading verified: 'ensemble' is None at startup.")
    else:
        print("[FAIL] Lazy loading failed: 'ensemble' is already initialized.")

except ImportError as e:
    print(f"ImportError during startup check: {e}")
except Exception as e:
    print(f"An error occurred during startup check: {e}")
