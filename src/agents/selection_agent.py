import re
import signal
import traceback
from zoneinfo import ZoneInfo
import google.generativeai as genai
import pandas as pd
import numpy as np

class TimeoutException(Exception):
    pass

def _timeout_handler(signum, frame):
    raise TimeoutException("LLM call timed out")

signal.signal(signal.SIGALRM, _timeout_handler)

class Selection_Strategist_Agent:
    def __init__(self, model_name='gemini-2.5-flash'):
        self.model = genai.GenerativeModel(model_name)
        
    def select_indicator_and_generate_code(self, strategy_desc_path, existing_strategies=None):
        print(f"[AI Agent] 전략 설명 파일 로딩 중: {strategy_desc_path}")
        excluded_strategies = ", ".join(existing_strategies) if existing_strategies else "None"
        try:
            with open(strategy_desc_path, 'r', encoding='utf-8') as f:
                strategy_description = f.read()
        except FileNotFoundError:
            print(f"[Error] 전략 설명 파일을 찾을 수 없습니다: {strategy_desc_path}")
            return None, None

        print("[AI Agent] 전략 컨텍스트를 분석하여 최적의 TA Indicator 선정 중...")

        prompt = f"""
        You are a professional crypto quant researcher.

        Your task is to generate ONE fast, robust indicator function
        to improve asset selection for the following strategy.

        ────────────────────────────────
        [Strategy Description]
        {strategy_description}

        [Context]
        - Timeframe: 15m data, selection every 1 hour
        - Goal: select top 3 assets per hour
        - Input data: OHLCV DataFrames (multi-symbol)
        ────────────────────────────────

        [Requirements]
        1. Propose ONE indicator (or integrated multi-factor as ONE output)
        2. Indicator must:
        - Be well-known (TradingView / common quant usage)
        - Be computable every 15 minutes
        - Improve win-rate relevance
        3. Do NOT overlap conceptually or by name with:
        {excluded_strategies}

        [Implementation Rules]
        - Implement exactly ONE function: calculate_indicator(...)
        - Inputs: opens, closes, highs, lows, volumes (DataFrames)
        - Output: DataFrame (same shape)
        - Fully vectorized (NO loops over symbols)
        - No NaN allowed (fill with 0 or forward-fill)
        - Use pandas / numpy / numba only
        - Do NOT use TA functions that require Series input

        [Output Format — MUST FOLLOW EXACTLY]
        Indicator Name: <NAME>
        <1–2 sentences explaining why this indicator fits>

        ```python
        <complete python code with imports>
        """ 

        signal.alarm(120)
        try:
            response = self.model.generate_content(prompt)
            content = response.text
            self.model_response_text = content
        except TimeoutException:
            print("⏱ [Timeout] LLM 응답 시간 초과 → 즉시 스킵")
            return None, None
        except Exception:
            print("❌ [Error] LLM 호출 실패")
            traceback.print_exc()
            return None, None
        finally:
            signal.alarm(0)

        name_match = re.search(r"Indicator Name:\s*(.+)", content)
        indicator_name = name_match.group(1).strip() if name_match else "Unnamed"
        code_blocks = re.findall(r"```(?:python|py)?\s*(.*?)```", content, re.DOTALL)
        selected_code = None
        for block in code_blocks:
            if "def calculate_indicator" in block:
                selected_code = block.strip()
                break
        if selected_code is None:
            print("[Error] calculate_indicator 함수가 포함된 코드가 없습니다.")
            return indicator_name, None

        explanation = content.split("```")[0].strip()
        print("\n" + "=" * 50)
        print(f"🤖 AI의 지표 선정 이유 ({indicator_name}):")
        print("-" * 20)
        print(explanation)
        print("=" * 50 + "\n")
        return indicator_name, selected_code

    def fix_indicator_code(self, code, error_log):
        prompt = f"""..."""  # 기존 오류 수정 prompt 그대로 사용
        response = self.model.generate_content(prompt)
        fixed_match = re.search(r"```(?:python|py)?\s*(.*?)```", response.text, re.DOTALL)
        if fixed_match:
            return fixed_match.group(1).strip()
        return code

    def generate_and_validate_indicator(self, strategy_desc_path, existing_strategies, market_data, max_retries=3):
        indicator_name, code = self.select_indicator_and_generate_code(strategy_desc_path, existing_strategies)
        if code is None:
            return indicator_name, None, None

        for attempt in range(max_retries):
            print(f"\n🚀 [Attempt {attempt+1}/{max_retries}] indicator 실행 중...  ({indicator_name})")
            try:
                scope = {}
                exec(code, scope)
                if "calculate_indicator" not in scope:
                    raise RuntimeError("calculate_indicator function missing after code generation.")
                calc_fn = scope["calculate_indicator"]
                indicator_df = calc_fn(
                    market_data["open"],
                    market_data["close"],
                    market_data["high"],
                    market_data["low"],
                    market_data["volume"]
                )
                print(f"✅ indicator 정상 계산 완료: {indicator_name}")
                return indicator_name, code, indicator_df
            except Exception as e:
                error_log = traceback.format_exc()
                print(f"\n❌ indicator 실행 실패! 오류 발생:")
                print(error_log)
                print("\n🔁 LLM에게 코드 자동 수정 요청합니다...")
                code = self.fix_indicator_code(code, error_log)

        print("\n❌ 모든 재시도 실패 — indicator 코드 수동 점검이 필요합니다.")
        return indicator_name, code, None