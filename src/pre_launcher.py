import os
import sys
import gc
import time
import textwrap
import pandas as pd
import numpy as np
import importlib.util
from tqdm import tqdm

# ------------------------------------------------------------------------------
# 1. 환경 설정 및 라이브러리 임포트
# ------------------------------------------------------------------------------
# 현재 파일 위치 기준 상위 폴더(루트)를 경로에 추가하여 모듈 import 가능하게 함

from config import * # DATA_DIR, PA_TRADE_FILE, RESULT_DIR, STRATEGY_DESC_PATH 등
from data.load_data import load_market_data, load_pa_trades
from agents.pre_agent import PreSelectionAgent

# ==============================================================================
# 2. Helper Functions
# ==============================================================================

def execute_generated_code(code_str, market_data):
    """
    LLM(Agent)이 생성한 파이썬 코드를 동적으로 실행하여
    전체 종목에 대한 Ranking Score DataFrame을 반환합니다.
    """
    try:
        # 가상의 모듈 생성
        module_spec = importlib.util.spec_from_loader("generated_ranker", loader=None)
        ranker_module = importlib.util.module_from_spec(module_spec)
        
        # 문자열 코드를 해당 모듈 네임스페이스에서 실행
        exec(code_str, ranker_module.__dict__)
        
        # 함수 호출 (opens, highs, lows, closes, volumes)
        scores = ranker_module.calculate_ranking_score(
            market_data['open'], 
            market_data['high'], 
            market_data['low'],
            market_data['close'], 
            market_data['volume']
        )
        return scores
    except Exception as e:
        print(f"❌ Execution Error in Agent Code: {e}")
        import traceback
        traceback.print_exc()
        return None

def calculate_ranking_metrics_from_group(current_trades_df, selected_symbols):
    """
    평가 로직 (중복 보너스 버전):
    1. Rank: 종목별 평균 순위 사용 (MAR 계산용)
    2. Hit: 종목별 발생한 거래 횟수만큼 Hit Count에 합산 (Hit Rate 계산용)
       -> 즉, 내가 고른 종목이 여러 번 매매 기회를 줬다면 Hit Rate가 올라감.
    """
    k = len(selected_symbols)
    if k == 0: return None
    
    # 1. 모든 거래 기록을 수익률 내림차순 정렬하여 개별 등수 매기기
    current_trades_df = current_trades_df.sort_values(by='return', ascending=False).copy()
    current_trades_df['individual_rank'] = range(1, len(current_trades_df) + 1)
    
    # 2. 종목(symbol)별로 '평균 순위(mean)'와 '거래 횟수(count)'를 계산
    # stats_df index: symbol, columns: mean, count
    stats_df = current_trades_df.groupby('symbol')['individual_rank'].agg(['mean', 'count'])
    
    # 검색 속도를 위해 딕셔너리로 변환
    # 예: {'BTC': {'mean': 2.5, 'count': 2}, 'ETH': {'mean': 5.0, 'count': 1}}
    stats_dict = stats_df.to_dict('index')
    
    actual_ranks = []
    total_hits = 0
    
    for sym in selected_symbols:
        if sym in stats_dict:
            data = stats_dict[sym]
            
            # [MAR용] 해당 종목의 평균 순위 기록
            # (여러 번 거래했어도 '성능'은 평균적으로 몇 등이었는지를 봄)
            actual_ranks.append(data['mean'])
            
            # [HitRate용] 발생한 거래 횟수만큼 Hit 추가
            # (한 종목이 2번 거래를 줬으면 2 Hit로 인정)
            total_hits += data['count']
        else:
            # 시그널 안 뜸
            pass
            
    # Hit Rate 계산 (Hit 수가 K보다 클 수도 있음. 예: 3개 뽑았는데 총 5번 거래 발생 시 166%)
    hit_rate = total_hits / k
    
    mar = np.mean(actual_ranks) if actual_ranks else np.nan 

    return {
        "Hit_Rate": hit_rate,
        "MAR": mar,
        "Hits": total_hits,
        "Actual_Ranks": actual_ranks,
        "Total_Signals": len(stats_dict) # 유니크 종목 수 기준
    }

# ==============================================================================
# 3. Main Execution
# ==============================================================================

def main():

    print("\n========================================")
    print("🚀 Pre-Selection Algorithm Evaluator")
    print("========================================\n")
    
    # 1. 데이터 로드 (기존 load_data 모듈 활용)
    print(f"📥 Loading Market Data from {DATA_DIR}...")
    market_data = load_market_data(DATA_DIR)

    # [★ 추가] 메모리 최적화: float64 -> float32 변환
    print("📉 Optimizing Memory (Downcasting to float32)...")
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in market_data:
            market_data[col] = market_data[col].astype('float32')
    
    print(f"📥 Loading PA Trades from {PA_TRADE_FILE}...")
    pa_trades_df = load_pa_trades(PA_TRADE_FILE)
    
    # 전략 설명 로드
    if os.path.exists(STRATEGY_DESC_PATH):
        with open(STRATEGY_DESC_PATH, 'r', encoding='utf-8') as f:
            strategy_desc = f.read()
    else:
        print(f"⚠️ Warning: Strategy description not found at {STRATEGY_DESC_PATH}. Using default.")
        strategy_desc = "General Crypto Trading Strategy"

    # ---------------------------------------------------------
    # [FIX] Symbol Alignment (종목 교집합 맞추기 - 안전장치)
    # ---------------------------------------------------------
    # Market Data와 PA Trades에 모두 존재하는 종목만 사용
    market_symbols = set(market_data['close'].columns)
    trade_symbols = set(pa_trades_df['symbol'].unique())
    common_symbols = sorted(list(market_symbols & trade_symbols))
    
    if not common_symbols:
        raise ValueError("❌ Market Data와 Trade Data 간 공통 종목이 없습니다.")
        
    print(f"🔗 Analysis Universe: {len(common_symbols)} symbols")

    # --------------------------------------------------------------------------
    # [★ 추가] 좀비 필터(상장폐지/거래정지) 마스크 미리 계산 (속도 최적화)
    # --------------------------------------------------------------------------
    print("🧟 Pre-calculating Zombie Asset Mask (Flatline & Delisted)...")
    # 1) 최근 24시간 가격 변동성(표준편차)이 0이면 좀비 (상폐되어 가격이 멈춤)
    # 2) 거래량이 0이어도 좀비
    # 3) 데이터가 NaN이어도 좀비
    close_std = market_data['close'].rolling(window=24, min_periods=1).std()
    
    # True = 죽은 종목 (점수 박탈 대상)
    # std == 0 (가격 불변) OR volume == 0 (거래 없음) OR close is NaN (데이터 없음)
    zombie_mask = (close_std == 0) | (market_data['volume'] == 0) | (market_data['close'].isna())
    
    print("   ✅ Zombie Mask Ready.")

    # --------------------------------------------------------------------------
    # [FIX] Oracle 구축 방식 변경: Pivot 대신 GroupBy 사용 (중복 데이터 처리)
    # --------------------------------------------------------------------------
    print("🔮 Pre-processing Oracle Data (Grouping by Anchor)...")
    # Pivot을 하면 중복 에러가 나므로, 미리 anchor별로 그룹핑해둡니다.
    # 이를 통해 나중에 루프 돌 때 빠르게 해당 시간대 데이터를 가져옵니다.
    pa_trades_grouped = pa_trades_df.groupby('anchor')
    
    # 평가 가능한 시간대 (Trades 데이터가 있는 시간들)
    valid_anchors = sorted(list(pa_trades_grouped.groups.keys()))
    print(f"   Found {len(valid_anchors)} anchors with trade signals.")

    # 기존 indicator 수집
    existing_indicators = []
    for bucket in ['pass','fail','hold']:
        bucket_dir = os.path.join(RESULT_DIR, bucket)
        if os.path.exists(bucket_dir):
            for name in os.listdir(bucket_dir):
                path = os.path.join(bucket_dir,name)
                if os.path.isdir(path):
                    existing_indicators.append(name)
    print(f"[Info] 현재 저장된 INDICATOR(총 이름 수): {len(existing_indicators)}개")

    # --------------------------------------------------------------------------
    # [2] 무한 루프 시작 (Agent 실행 -> 평가 -> 저장 반복)
    # --------------------------------------------------------------------------
    loop_count = 1
    
    while True:

        try:

            # 3. Agent 실행
            print(f"\n🔄 [Loop {loop_count}] Starting New Generation Cycle...")
            print("🤖 Requesting Agent to generate ranking algorithm...")
            agent = PreSelectionAgent()
            algo_name, algo_logic, algo_code = agent.generate_ranking_code(strategy_desc, market_data, existing_indicators)

            # ★ [수정 1] 코드가 None이면 즉시 다음 루프로 건너뛰기 (방어 로직 추가)
            if algo_code is None:
                print("⚠️ Code generation failed (None returned). Retrying in 3 seconds...")
                time.sleep(3)
                continue  # <--- 여기서 continue가 없으면 밑에서 에러남

            print(f"   🔹 Algorithm Name: {algo_name}")

            # 4. Score 계산
            print("⚙️  Calculating Ranking Scores for ALL assets...")
            score_df = execute_generated_code(algo_code, market_data)
            
            if score_df is None:
                print("❌ Score calculation failed. Skipping...")
                time.sleep(3)
                continue  # <--- 기존 코드에 혹시 return이 되어있는지 확인하세요!

            # 인덱스 정렬 (Oracle 시간축과 맞추기 위해 reindex)
            # Trades에 있는 시간만 남기는 게 아니라, 전체 시간을 유지하되 평가 시 교집합만 사용
            score_df = score_df.reindex(pd.to_datetime(valid_anchors)).ffill().fillna(-999)

            # 5. 평가 루프
            print("⚖️  Evaluating Selection Quality (Ranking)...")
            
            eval_logs = []
            
            # 실제 Score 데이터와 Trade 데이터가 모두 존재하는 시간만 순회
            # (이미 valid_anchors가 Trade 기준이므로, Score Index와 교집합 확인)
            score_anchors = score_df.index
            eval_targets = sorted(list(set(valid_anchors) & set(score_anchors)))
            
            for t in tqdm(eval_targets, desc="Evaluator"):# [★ 핵심 수정 1] 매 루프마다 변수 초기화 (이전 값 잔재 방지)
                
                row_scores = score_df.loc[t]
                current_zombies = zombie_mask.loc[t]
                valid_row = row_scores[~current_zombies]
                valid_row = valid_row[valid_row > -900]
                
                if valid_row.empty: 
                    continue
                    
                # 상위 3개 선정
                top_10_symbols = valid_row.nlargest(10).index.tolist()
                # 평가는 기존 로직 유지를 위해 Top 3만 사용
                top_3_for_eval = top_10_symbols[:3]
                
                # B. 정답 확인 (Oracle)
                try:
                    current_trades = pa_trades_grouped.get_group(t)
                except KeyError:
                    continue 
                    
                if current_trades.empty: continue
                    
                # C. 채점 (중복 허용 로직 사용)
                metrics = calculate_ranking_metrics_from_group(current_trades, top_3_for_eval)
                
                if metrics:
                    eval_logs.append({
                        "timestamp": t,
                        "selected_symbols": str(top_10_symbols),
                        "hit_rate": metrics["Hit_Rate"],
                        "mar": metrics["MAR"],
                        "hits": metrics["Hits"],
                        "actual_ranks": str(metrics["Actual_Ranks"]),
                        "n_candidates": metrics["Total_Signals"]
                    })

            # 6. 결과 저장
            if not eval_logs:
                print("❌ No valid evaluation periods found.")
                return

            df_eval = pd.DataFrame(eval_logs)

            # hold 디렉토리 생성
            hold_dir = os.path.join(RESULT_DIR, "hold")
            os.makedirs(hold_dir, exist_ok=True)
            
            # 알고리즘별 저장 경로
            save_path = os.path.join(hold_dir, algo_name.replace(" ", "_"))
            os.makedirs(save_path, exist_ok=True)
            
            # CSV 저장
            df_eval.to_csv(os.path.join(save_path, "Selection_Evaluation_Trades.csv"), index=False)
            
            # [2] 최종 통계 계산
            avg_mar = df_eval['mar'].mean()
            avg_hit = df_eval['hit_rate'].mean()
            total_trades = df_eval['hits'].sum()
            total_samples = len(df_eval)

            # [3] 요약 메트릭 저장 (Summary_Metrics.csv) - ★ 추가된 부분
            summary_data = {
                "Algorithm_Name": [algo_name],
                "Logic": [algo_logic],
                "Total_Anchors": [total_samples],
                "Avg_Hit_Rate": [avg_hit],
                "Avg_MAR": [avg_mar],
                "Total_Trades": [total_trades]
            }

            pd.DataFrame(summary_data).to_csv(os.path.join(save_path, "Summary_Metrics.csv"), index=False)

            # [4] 알고리즘 설명 및 결과 텍스트 저장 - ★ 수정된 부분
            with open(os.path.join(save_path, "Algorithm_Description.txt"), "w", encoding="utf-8") as f:
                f.write(f"Algorithm Name: {algo_name}\n")
                f.write(f"Logic: {algo_logic}\n")
                f.write("-" * 60 + "\n")
                f.write("📊 Final Evaluation Metrics\n")
                f.write("-" * 60 + "\n")
                f.write(f"Total Trades   : {total_trades}\n")
                f.write(f"Avg Hit Rate    : {avg_hit*100:.2f}%\n")
                f.write(f"Avg MAR (Rank)  : {avg_mar:.4f}\n")
                f.write("=" * 60 + "\n\n")
                f.write(f"Target Strategy Description:\n{strategy_desc[:500]}...\n\n")
                f.write("-" * 60 + "\n")
                f.write(f"Generated Code:\n{algo_code}")

            # 콘솔 출력
            print("\n" + "="*60)
            print(f"📊 Final Evaluation Report: {algo_name}")
            print("="*60)
            print(f"Total_Trades : {total_trades}")
            print("-" * 60)
            print(f"🎯 Signal Hit Rate      : {avg_hit * 100:.2f}%")
            print("-" * 60)
            print(f"🏅 MAR (Mean Avg Rank)  : {avg_mar:.2f} (Lower is Better)")
            print("="*60)
            print(f"✅ Results saved to: {save_path}")

            # 다음 루프 준비
            loop_count += 1
            
            # API Rate Limit 등을 고려한 대기 시간
            print("⏳ Waiting 3 seconds before next generation...")
            time.sleep(3)
            
            # 메모리 정리
            del score_df
            gc.collect()

        except KeyboardInterrupt:
            print("\n🛑 Stopped by User (KeyboardInterrupt).")
            break
        except Exception as e:
            print(f"\n❌ Unexpected Error in Loop {loop_count}: {e}")
            import traceback
            traceback.print_exc()
            print("⚠️ Retrying in 10 seconds...")
            time.sleep(10)

if __name__ == "__main__":
    main()