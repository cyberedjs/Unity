import os
import faiss
import warnings
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

# =========================
# Paths
# =========================
BASE_DIR = "/Users/cyberedjs/Desktop/Unity/data"
DATA_DIR = os.path.join(BASE_DIR, "combined")
STRATEGY_NAME = "Volume-Validated Impulse EMA Momentum (VVIEM)"
RESULT_DIR = f"/Users/cyberedjs/Desktop/Unity/results/backtest_results/{STRATEGY_NAME}"
PA_TRADE_FILE = f"/Users/cyberedjs/Desktop/Unity/results/pa_trade_results/Momentum/priority/{STRATEGY_NAME}/PA_All_Trades.csv"
STRATEGY_DESC_PATH = f"/Users/cyberedjs/Desktop/Unity/results/pa_trade_results/Momentum/priority/{STRATEGY_NAME}/Strategy_Description.txt"
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# =====================
# Backtest Params
# =====================
LOOKBACK_WINDOW = 20
ROLLING_WINDOW = 96     
TOP_N_EUCLIDEAN = 100   
TOP_K_DTW = 30
MIN_SAMPLES = 30

warnings.filterwarnings("ignore")
os.makedirs(RESULT_DIR, exist_ok=True)
genai.configure(api_key=GOOGLE_API_KEY)

