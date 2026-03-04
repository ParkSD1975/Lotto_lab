import sys
import os
sys.path.append(r'c:\Users\psdet\Desktop\로또개발\langchain-backend')

from models.autoencoder_model import AutoencoderTrainer
from models.cnn_model import CNNTrainer
from models.gnn_model import GNNTrainer

print("Testing Autoencoder Predict:")
ae = AutoencoderTrainer()
res_ae = ae.predict([])
print("Autoencoder keys:", len(res_ae.keys()), "Sum:", sum(res_ae.values()), "Sample:", list(res_ae.values())[:5])

print("\nTesting CNN Predict:")
cnn = CNNTrainer()
res_cnn = cnn.predict([])
print("CNN keys:", len(res_cnn.keys()), "Sum:", sum(res_cnn.values()), "Sample:", list(res_cnn.values())[:5])

print("\nTesting GNN Predict:")
gnn = GNNTrainer()
res_gnn = gnn.predict([])
print("GNN keys:", len(res_gnn.keys()), "Sum:", sum(res_gnn.values()), "Sample:", list(res_gnn.values())[:5])
