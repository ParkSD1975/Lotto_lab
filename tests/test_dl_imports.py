import sys
import os

# Add project root to sys.path
sys.path.append(os.path.join(os.getcwd(), 'langchain-backend'))

print("Testing imports...")
try:
    import config
    print("Config imported.")
    
    from models.focal_loss import FocalLoss
    print("FocalLoss imported.")
    
    from models.lstm_model import LottoLSTM
    print("LottoLSTM imported.")
    
    from models.cnn_model import LottoCNN
    print("LottoCNN imported.")
    
    from models.transformer_model import LottoTransformer
    print("LottoTransformer imported.")
    
    from models.ensemble import LottoEnsemble
    print("LottoEnsemble imported.")
    
    print("\nTesting Model Instantiation...")
    lstm = LottoLSTM()
    print("LSTM Instantiated.")
    
    cnn = LottoCNN()
    print("CNN Instantiated.")
    
    trans = LottoTransformer()
    print("Transformer Instantiated.")
    
    print("\n[SUCCESS] All Deep Learning Models passed syntax check.")
    
except Exception as e:
    print(f"\n[FAIL] Error during verification: {e}")
    import traceback
    traceback.print_exc()
