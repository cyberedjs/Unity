import os
import warnings
import pandas as pd
import quantstats as qs

from pa_config import *
from data.load_data import load_market_data
from pa_backtester import execute_strategy
from agents.pa_agent import PA_Architect_Agent

warnings.filterwarnings('ignore')

def main():
    # 1. 초기화 및 폴더 생성
    
    for status in STATUS_DIRS:
        os.makedirs(os.path.join(RESULT_DIR, status), exist_ok=True)
    
    # ------------------------------------------------------------------
    # [수정됨] 기존 전략 스캔: 4개 폴더 모두 확인
    # ------------------------------------------------------------------
    existing_strategies = []
    
    print("[Info] Scanning existing strategies...")
    for status in STATUS_DIRS:
        status_dir = os.path.join(RESULT_DIR, status)
        if os.path.exists(status_dir):
            # 폴더 내의 하위 디렉토리(전략 이름)들을 가져옴
            for name in os.listdir(status_dir):
                full_path = os.path.join(status_dir, name)
                # 시스템 파일(.DS_Store 등) 제외하고 디렉토리만 추가
                if os.path.isdir(full_path):
                    existing_strategies.append(name)
    
    # 중복 제거 (혹시 모를 상황 대비)
    existing_strategies = list(set(existing_strategies))
    
    # 2. 데이터 로드
    market_data = load_market_data(DATA_DIR)
    if not market_data: return

    agent = PA_Architect_Agent()

    while True:
        print("\n" + "="*60)
        print(f"🚀 New Strategy Generation... (Count: {len(existing_strategies)})")
        
        # 3. 전략 생성
        name, desc, code = agent.search_and_generate_strategy(STRATEGY_TYPE, existing_strategies)
        
        if not code:
            print("❌ Code generation failed.")
            continue

        # 4. 백테스트 및 에러 수정 루프 (최대 3회)
        trades_df = None
        for attempt in range(3):
            try:
                print(f"   [Attempt {attempt+1}] Executing Strategy: {name}")
                trades_df = execute_strategy(market_data, code)
                
                if trades_df is not None and not trades_df.empty:
                    break # 성공
                
                # 거래가 없거나 실패 시
                print("   ⚠️ No trades or Execution Error. Requesting Fix...")
                code = agent.fix_code(code, "No trades generated or execution error. Relax conditions.")
                
            except Exception as e:
                import traceback
                err = traceback.format_exc()
                print(f"   [Error] {str(e)}")
                code = agent.fix_code(code, err)

        # 5. 결과 저장 (성공 시)
        if trades_df is not None and not trades_df.empty:
            print(f"✅ Success! Trades: {len(trades_df)}")
            
            # 폴더 생성
            save_path = os.path.join(RESULT_DIR, "hold", name)
            os.makedirs(save_path, exist_ok=True)
            
            # 설명 저장
            with open(f"{save_path}/Strategy_Description.txt", "w") as f:
                f.write(desc)
            
            # 코드 저장 (나중에 디버깅용)
            with open(f"{save_path}/code.py", "w") as f:
                f.write(code)

            # 전체 거래 내역 (Anchor 추가)
            trades_df['anchor'] = trades_df['entry_time'].dt.floor('H')
            trades_df.to_csv(f"{save_path}/PA_All_Trades.csv", index=False)
            
            # Top 3 거래
            top3 = trades_df.groupby('anchor').apply(lambda x: x.nlargest(3, 'return')).reset_index(drop=True)
            top3.to_csv(f"{save_path}/PA_Top3_Trades.csv", index=False)
            
            # 리포트
            try:
                # 간단한 시계열 수익 곡선 생성
                aum = (top3.set_index('exit_time').sort_index()['return'] * 1000).cumsum() + 10000
                aum_daily = aum.resample('D').last().ffill()
                qs.reports.html(aum_daily.pct_change(), output=f"{save_path}/PA_Report.html", title=name)
            except:
                print("   [Warning] Report generation failed (not enough data).")
            
            existing_strategies.append(name)
        else:
            print("❌ Failed after retries.")
            existing_strategies.append(name) # 실패한 이름도 추가해서 중복 생성 방지

if __name__ == "__main__":
    main()