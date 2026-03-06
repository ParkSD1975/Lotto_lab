import sys
import traceback
sys.path.append(r'c:\Users\psdet\Desktop\로또개발\langchain-backend')

try:
    from models.cnn_model import CNNTrainer
    from models.gnn_model import GNNTrainer
    from models.autoencoder_model import AutoencoderTrainer

    print("Checking CNN...")
    cnn = CNNTrainer()
    cnn._load_model()
    if cnn.model is None: print('CNN model failed to load')
    else: print('CNN model loaded')

    print("Checking GNN...")
    gnn = GNNTrainer()
    gnn._load_model()
    if gnn.model is None: print('GNN model failed to load')
    else: print('GNN model loaded')

    print("Checking Autoencoder...")
    ae = AutoencoderTrainer()
    ae._load_model()
    if getattr(ae, 'model', None) is None: print('AE model failed to load')
    else: print('AE model loaded')
except Exception as e:
    traceback.print_exc()
