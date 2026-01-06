import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# 경로 설정
BASE_DIR = "/Users/cyberedjs/Desktop/Unity/data"
DATA_DIR = os.path.join(BASE_DIR, "combined")
RESULT_DIR = "/Users/cyberedjs/Desktop/Unity/results/pa_trade_results/Momentum"

STATUS_DIRS = ["pass", "fail", "hold", "priority"]
STRATEGY_TYPE = "Momentum"

# 백테스트 설정
FEE_RATE = 0.0005  # 0.05% (진입 시, 청산 시 각각 적용 -> 총 0.1%)
TOTAL_FEE = FEE_RATE * 2