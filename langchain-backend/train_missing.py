import sys
import traceback
sys.path.append(r'c:\Users\psdet\Desktop\로또개발\langchain-backend')

try:
    from models.cnn_model import CNNTrainer
    from models.autoencoder_model import AutoencoderTrainer
    from db.repository import get_all_draws
    
    print("Loading draws...")
    draws = get_all_draws()
    draws = [d for d in draws if 'round' in d]
    draws = sorted(draws, key=lambda x: x['round'])

    print("Training CNN...")
    cnn = CNNTrainer()
    res = cnn.train(draws, fine_tune=False)
    print("CNN trained:", res)

    print("Training Autoencoder...")
    ae = AutoencoderTrainer()
    res2 = ae.train(draws)
    print("AE trained:", res2)

except Exception as e:
    traceback.print_exc()
