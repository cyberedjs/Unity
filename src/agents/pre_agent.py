import re
import signal
import traceback
import google.generativeai as genai
import pandas as pd
import numpy as np

# ------------------------------------------------------------------------------
# Timeout Handling (기존 코드와 동일)
# ------------------------------------------------------------------------------
class TimeoutException(Exception):
    pass

def _timeout_handler(signum, frame):
    raise TimeoutException("LLM call timed out")

signal.signal(signal.SIGALRM, _timeout_handler)

# ------------------------------------------------------------------------------
# PreSelectionAgent Class
# ------------------------------------------------------------------------------
class PreSelectionAgent:
    def __init__(self, model_name='gemini-2.5-flash'):
        """
        Gemini 모델 초기화
        """
        self.model = genai.GenerativeModel(model_name)
        self.model_response_text = ""

    def _call_llm_and_parse(self, strategy_description, existing_indicators):
        """
        LLM에게 프롬프트를 보내고, 응답에서 이름, 로직, 코드를 파싱합니다.
        """
        excluded_algos = ", ".join(existing_indicators) if existing_indicators else "None"
        print("[AI Agent] 전략 컨텍스트를 분석하여 최적의 Ranking Algorithm 선정 중...")

        prompt = f"""
        You are a professional crypto quant researcher specializing in "Asset Ranking".

        Your task is to generate ONE Python function (`calculate_ranking_score`) that ranks ALL available assets to find the best environment for a specific Price Action Strategy.

        ────────────────────────────────
        [Target Strategy Description]
        The user will apply the following Fixed Price Action Signal *AFTER* your selection:
        
        "{strategy_description}"

        [Your Role & Context]
        1. **Pre-Filter Logic**: You are NOT detecting the signal itself. You are ranking assets to find those **most likely to perform well** IF the signal occurs.
        2. **Universe**: You must rank ALL assets in the provided DataFrames, regardless of whether they have a signal right now.
        3. **Logic**: 
           - Signal is based on 15m TIMEFRAME and Asset Selection is in EVERY 1H.
           - You need to find the best candidate that will result in best outcome IF THE PRICE ACTION SIGNAL OCCURS.
           - Candidate Selection SHOULD NOT RELY ON LONG TERM METRICS. (Selected candidates shouldn't be same for long term)
           - New algorithm MUST HAVE LOW CORRELATION to exisiting algos: {excluded_algos}
           - USE UNIQUE & CREATIVE ALGOS THAT CAN RESULT IN LOW CORRELATION ALPHA POOLS.
        4. **Output**: A generic scoring DataFrame. Higher Score = Better Rank (Priority).

        [Implementation Rules]
        - **Implement exactly ONE function**: `calculate_ranking_score(...)`
        - **Arguments**: `opens`, `highs`, `lows`, `closes`, `volumes` (All are pd.DataFrame, index=datetime, columns=symbol)
        - **Return**: `scores` (pd.DataFrame, same shape as inputs).
        - **Vectorized**: Use pandas/numpy/numba. NO loops over symbols.
        - **Fillna**: Handle NaNs (e.g., fill with 0 or -999 for low priority).
        
        [Output Format — MUST FOLLOW EXACTLY]
        Indicator Name: <NAME>
        Logic: <1 sentence explaining why this ranking logic fits the strategy>
        
        ```python
        <complete python code with imports>
        ```
        """

        signal.alarm(120) # 120초 제한
        try:
            response = self.model.generate_content(prompt)
            content = response.text
            self.model_response_text = content
        except TimeoutException:
            print("⏱ [Timeout] LLM 응답 시간 초과")
            return None, None, None
        except Exception:
            print("❌ [Error] LLM 호출 실패")
            traceback.print_exc()
            return None, None, None
        finally:
            signal.alarm(0)

        # 1. Parsing Name
        name_match = re.search(r"Indicator Name:\s*(.+)", content)
        algo_name = name_match.group(1).strip() if name_match else "Unnamed_Ranker"

        # 2. Parsing Logic
        logic_match = re.search(r"Logic:\s*(.+)", content)
        algo_logic = logic_match.group(1).strip() if logic_match else "No explanation provided."

        # 3. Parsing Code
        code_blocks = re.findall(r"```(?:python|py)?\s*(.*?)```", content, re.DOTALL)
        selected_code = None
        for block in code_blocks:
            if "def calculate_ranking_score" in block:
                selected_code = block.strip()
                break
        
        if selected_code is None:
            print("[Error] calculate_ranking_score 함수가 포함된 코드가 없습니다.")
            return algo_name, algo_logic, None

        print("\n" + "=" * 50)
        print(f"🤖 AI의 랭킹 알고리즘 제안 ({algo_name}):")
        print("-" * 20)
        print(f"Logic: {algo_logic}")
        print("=" * 50 + "\n")

        return algo_name, algo_logic, selected_code

    def fix_ranking_code(self, code, error_log):
        """
        실행 에러 발생 시 LLM에게 수정 요청
        """
        prompt = f"""
        The following Python code for `calculate_ranking_score` failed during execution.
        
        [Error Log]
        {error_log}
        
        [Failed Code]
        ```python
        {code}
        ```
        
        [CRITICAL FIX INSTRUCTIONS]
        1. Keep the function signature EXACTLY as: 
           `def calculate_ranking_score(opens, highs, lows, closes, volumes):`
        2. Do NOT change input arguments. The system ALWAYS passes 5 DataFrames.
        3. Fix the specific error mentioned in the log.
        
        Output ONLY the fixed Python code block.
        """
        
        try:
            response = self.model.generate_content(prompt)
            fixed_match = re.search(r"```(?:python|py)?\s*(.*?)```", response.text, re.DOTALL)
            if fixed_match:
                return fixed_match.group(1).strip()
        except Exception as e:
            print(f"⚠️ 코드 수정 중 오류 발생: {e}")
        
        return code

    def generate_ranking_code(self, strategy_description, market_data=None, existing_indicators=None, max_retries=3):
        """
        [Main Entry Point]
        1. LLM에게 코드 생성 요청
        2. 생성된 코드가 실제 실행 가능한지(Validation) 테스트
        3. 성공 시 (Name, Logic, Code) 반환
        """
        
        # 1. Generate
        algo_name, algo_logic, code = self._call_llm_and_parse(strategy_description, existing_indicators)
        
        if code is None:
            return algo_name, algo_logic, None

        # market_data가 없으면 검증 없이 코드만 반환 (하지만 pre_launcher에서는 보통 데이터를 넘겨주는게 좋음)
        if market_data is None:
            print("⚠️ Market Data가 제공되지 않아 코드 검증을 건너뜁니다.")
            return algo_name, algo_logic, code

        # 2. Validation Loop
        for attempt in range(max_retries):
            print(f"\n🚀 [Attempt {attempt+1}/{max_retries}] 랭킹 알고리즘 검증 중... ({algo_name})")
            try:
                scope = {}
                # 필요한 라이브러리 스코프에 주입 (안전장치)
                scope['pd'] = pd
                scope['np'] = np
                
                exec(code, scope)
                
                if "calculate_ranking_score" not in scope:
                    raise RuntimeError("calculate_ranking_score function missing after execution.")
                
                calc_fn = scope["calculate_ranking_score"]
                
                # 실제 데이터로 테스트 실행
                # (메모리 절약을 위해 데이터의 일부만 잘라서 테스트할 수도 있음)
                test_len = 100
                input_close = market_data["close"].tail(test_len)
                
                test_scores = calc_fn(
                    market_data["open"].tail(test_len),
                    market_data["high"].tail(test_len),
                    market_data["low"].tail(test_len),
                    market_data["close"].tail(test_len),
                    market_data["volume"].tail(test_len)
                )
                
                # 결과 타입 및 Shape 확인
                if not isinstance(test_scores, pd.DataFrame):
                    raise TypeError("Output must be a pandas DataFrame.")
                
                # ------------------------------------------------------------------
                # [★ 핵심 수정] Shape Mismatch 방지 로직 (Reindexing)
                # ------------------------------------------------------------------
                # LLM이 만든 로직이 연산 과정에서 죽은 종목을 살려내거나(NaN),
                # 없던 컬럼을 만들 수도 있음. 따라서 '입력 데이터의 컬럼'을 기준으로 강제 정렬함.
                
                expected_cols = input_close.columns
                expected_shape = input_close.shape
                
                # 입력에 없는 컬럼은 버리고, 입력에 있는데 결과에 없으면 NaN으로 채움
                test_scores = test_scores.reindex(columns=expected_cols)
                
                # 2) Shape 재확인 (이제는 행(Row) 개수만 맞으면 통과)
                if test_scores.shape != expected_shape:
                     raise ValueError(f"Shape mismatch after reindexing. Expected {expected_shape}, got {test_scores.shape}")
                # ------------------------------------------------------------------

                print(f"✅ 알고리즘 정상 동작 확인 완료: {algo_name}")
                return algo_name, algo_logic, code

            except Exception as e:
                error_log = traceback.format_exc()
                print(f"\n❌ 알고리즘 실행 실패! 오류 발생:")
                print(error_log)
                print("\n🔁 LLM에게 코드 자동 수정 요청합니다...")
                
                # 코드 수정 시도
                code = self.fix_ranking_code(code, error_log)

        print("\n❌ 모든 재시도 실패 — 랭킹 알고리즘 코드 수동 점검이 필요합니다.")
        return algo_name, algo_logic, None