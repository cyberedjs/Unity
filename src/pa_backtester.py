import numpy as np
import pandas as pd
from numba import njit
from pa_config import FEE_RATE

@njit(fastmath=True)
def _run_backtest_numba(n_times, n_symbols, signals, opens, highs, lows, closes, times_int):
    """
    Numba로 가속화된 이벤트 기반 백테스팅 엔진 (t+1 Open 진입 로직 적용)
    """
    # 결과 저장용 배열 (넉넉하게 할당)
    max_trades = int(n_times * n_symbols * 0.5)
    # [sym_idx, entry_time, exit_time, entry_price, exit_price, direction, return, run_up, run_down]
    records = np.empty((max_trades, 9), dtype=np.float64)
    count = 0
    
    # 수수료 배수 (Long: 수익감소, Short: 수익감소) -> 수익률에서 빼는 방식 적용
    
    for j in range(n_symbols):
        curr_pos = 0        # 0: None, 1: Long, -1: Short
        entry_idx = -1
        entry_price = 0.0
        
        # Run-up / Run-down 추적용
        highest_price = -1.0 # 초기화
        lowest_price = 99999999.0 # 초기화
        
        # 시간 루프 (0 ~ T-2 까지 돌면서, t+1 시점에 행동)
        # 마지막 t에는 t+1이 없으므로 T-1까지만 루프
        for t in range(n_times - 1):
            
            sig = signals[t, j]     # t 시점의 시그널 (Close[t] 보고 생성됨)
            
            # 다음 캔들(t+1) 데이터
            next_open = opens[t+1, j]
            next_high = highs[t+1, j]
            next_low  = lows[t+1, j]
            next_close = closes[t+1, j]
            
            # 데이터 유효성 체크
            if next_open == 0: continue

            # -------------------------------------
            # 1. 포지션이 없는 경우 (진입 로직)
            # -------------------------------------
            if curr_pos == 0:
                if sig != 0:
                    # 진입 실행 (Open t+1)
                    curr_pos = sig
                    entry_idx = t + 1
                    entry_price = next_open
                    
                    # Run-up/down 초기화 (t+1 캔들부터 시작)
                    highest_price = next_high
                    lowest_price = next_low
            
            # -------------------------------------
            # 2. 포지션이 있는 경우 (청산 로직 및 추적)
            # -------------------------------------
            else:
                # A. Run-up / Run-down 갱신 (t+1 캔들의 High/Low 반영)
                if next_high > highest_price: highest_price = next_high
                if next_low < lowest_price: lowest_price = next_low
                
                # B. 청산 조건 확인
                # 시그널이 0으로 바뀌었거나, 방향이 달라지면 청산
                # (스위칭 없음 -> 일단 청산만 하고 이번 턴 종료)
                if sig == 0 or sig != curr_pos:
                    exit_price = next_open # t+1 시가 청산
                    
                    # 수익률 계산 (수수료 0.1% 반영: 진입 0.05 + 청산 0.05)
                    # 수수료 차감 방식: 순수익률 - 수수료총합
                    if curr_pos == 1: # Long
                        raw_ret = (exit_price - entry_price) / entry_price
                        run_up = (highest_price - entry_price) / entry_price
                        run_down = (lowest_price - entry_price) / entry_price
                    else: # Short
                        raw_ret = (entry_price - exit_price) / entry_price
                        run_up = (entry_price - lowest_price) / entry_price # Short은 가격 하락이 이득(Run-up)
                        run_down = (entry_price - highest_price) / entry_price # 가격 상승이 손실(Run-down)

                    net_ret = raw_ret - (FEE_RATE * 2) # 왕복 수수료 차감

                    # 기록 저장
                    if count < max_trades:
                        records[count, 0] = float(j)
                        records[count, 1] = float(times_int[entry_idx])
                        records[count, 2] = float(times_int[t+1]) # Exit Time
                        records[count, 3] = entry_price
                        records[count, 4] = exit_price
                        records[count, 5] = float(curr_pos)
                        records[count, 6] = net_ret
                        records[count, 7] = run_up
                        records[count, 8] = run_down
                        count += 1
                    
                    # 포지션 초기화
                    curr_pos = 0
                    entry_price = 0.0

    return records[:count]

def execute_strategy(data_dict, strategy_code):
    """
    전략 코드를 실행하고 Numba 백테스터를 호출
    """
    # 1. 전략 코드 실행 및 generate_signals 함수 확보
    exec_scope = {'np': np, 'pd': pd} # 라이브러리 주입
    
    try:
        exec(strategy_code, exec_scope)
        if 'generate_signals' not in exec_scope:
            raise ValueError("generate_signals 함수가 없습니다.")
        
        generate_signals = exec_scope['generate_signals']
        
        # 2. 시그널 생성
        signals_df = generate_signals(
            data_dict['open'], data_dict['high'], data_dict['low'],
            data_dict['close'], data_dict['volume']
        )
        
        # Shape 체크 및 포맷팅
        signals_df = signals_df.reindex(data_dict['close'].index).fillna(0).astype(np.int8)

    except Exception as e:
        print(f"[Error] 전략 실행 중 오류: {e}")
        return None

    # 3. 데이터 준비 (Numpy 변환)
    opens = data_dict['open'].values.astype(np.float64)
    highs = data_dict['high'].values.astype(np.float64)
    lows = data_dict['low'].values.astype(np.float64)
    closes = data_dict['close'].values.astype(np.float64)
    
    signals = signals_df.values
    times_int = data_dict['close'].index.astype(np.int64).values # Int64로 변환

    n_times, n_symbols = closes.shape

    # 4. Numba 백테스팅 실행
    raw_records = _run_backtest_numba(
        n_times, n_symbols, signals, opens, highs, lows, closes, times_int
    )

    if len(raw_records) == 0:
        return pd.DataFrame()

    # 5. 결과 DataFrame 변환
    columns = data_dict['close'].columns
    df_trades = pd.DataFrame(raw_records, columns=[
        'sym_idx', 'entry_time_int', 'exit_time_int', 
        'entry_price', 'exit_price', 'direction', 'return', 'run_up', 'run_down'
    ])

    # 메타데이터 복원
    df_trades['symbol'] = df_trades['sym_idx'].astype(int).map(lambda x: columns[x])
    df_trades['entry_time'] = pd.to_datetime(df_trades['entry_time_int'])
    df_trades['exit_time'] = pd.to_datetime(df_trades['exit_time_int'])
    
    # 컬럼 정리
    result_cols = [
        'symbol', 'entry_time', 'exit_time', 'direction', 
        'entry_price', 'exit_price', 'return', 'run_up', 'run_down'
    ]
    return df_trades[result_cols]