import sys
import os

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    print("Testing imports...")
    from models.cnn_model import CNNTrainer
    from models.autoencoder_model import AutoencoderTrainer
    from models.ensemble import LottoEnsemble
    print("Imports successful.")

    print("Initializing classes...")
    cnn = CNNTrainer()
    ae = AutoencoderTrainer()
    ensemble = LottoEnsemble()
    print("Classes initialized successfully.")
    
    print("Verification complete.")

except Exception as e:
    print(f"Verification failed: {e}")
    sys.exit(1)
