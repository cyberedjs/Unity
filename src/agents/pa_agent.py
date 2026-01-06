import re
import google.generativeai as genai

from pa_config import GOOGLE_API_KEY

genai.configure(api_key=GOOGLE_API_KEY)

class PA_Architect_Agent:
    def __init__(self, model_name='gemini-2.5-flash'):
        self.model = genai.GenerativeModel(model_name)

    def search_and_generate_strategy(self, strategy_type, existing_strategies):
        excluded = ", ".join(existing_strategies) if existing_strategies else "None"
        
        prompt = f"""
        You are an expert Crypto Quant Researcher.
        Generate ONE Python trading strategy ({strategy_type}) for 15m candles.
        
        Existing strategies to avoid: {excluded}

        The strategy MUST:
        - BE ORTHOGONAL or HAS LOW CORRELATION to existing strategies
        - Work on 15-minute OHLCV crypto data
        - Have BOTH ENTRY AND EXIT LOGIC CLEARLY DEFINED (NO STOP-LOSS OR TRAILING STOP BASED EXIT LOGIC)
        - Use only numpy vectorized operations (NO Python loops)

        ============================================================
        CODE STRUCTURE RULES
        ============================================================
        1. You MUST include `import numpy as np` and `import pandas as pd`.
        2. Define a function: `def generate_signals(opens, highs, lows, closes, volumes):`
        3. INPUTS: Pandas DataFrames (Index=Datetime, Columns=Symbols).
        4. OUTPUT: A Pandas DataFrame of signals (-1, 0, 1) with the same shape.
           - 1: Long Signal
           - -1: Short Signal
           - 0: Exit / No Position
        5. LOGIC: 
           - Use ONLY vectorized operations (NumPy/Pandas). NO LOOPS.
           - **NO LOOK-AHEAD BIAS**: Calculate signal at index `t` using data only up to `t`.
           - The backtester will execute the trade at `Open[t+1]`.
           - Do NOT implement the trade execution logic (fees, PnL), ONLY the signal generation.
        
        ============================================================
        OUTPUT FORMAT
        ============================================================
        Strategy Name: <Name>
        Description: <Short Description>
        
        ```python
        import numpy as np
        import pandas as pd

        def generate_signals(opens, highs, lows, closes, volumes):
            # ... implementation ...
            return signals
        ```
        """
        
        try:
            response = self.model.generate_content(prompt)
            content = response.text
            
            name_match = re.search(r"Strategy Name:\s*(.+)", content)
            strategy_name = name_match.group(1).strip() if name_match else f"{strategy_type}_Unnamed"
            
            code_match = re.search(r"```python\n(.*?)```", content, re.DOTALL)
            code = code_match.group(1).strip() if code_match else None
            
            return strategy_name, content, code
        except Exception as e:
            print(f"[Agent Error] {e}")
            return None, None, None

    def fix_code(self, code, error_log):
        prompt = f"""
        Fix this Python code based on the error.
        Error: {error_log}
        
        Code:
        ```python
        {code}
        ```
        Return only the fixed code block.
        """
        try:
            resp = self.model.generate_content(prompt)
            match = re.search(r"```python\n(.*?)```", resp.text, re.DOTALL)
            return match.group(1).strip() if match else code
        except:
            return code