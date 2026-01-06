# Unity

Multi-Agents LLM Trading Framework

🏗️ System Architecture
본 프레임워크는 알파의 발견부터 실거래까지 전 과정을 자동화하는 목적으로 설계하였습니다.
**'알파 발굴(Alpha Discovery)'**과 '리스크 관리(Risk Execution)' 등의 단계를 구조적으로 분리하여, 전략의 통계적 유의성을 검증한 후 자금 관리 로직을 적용하는 모듈식 파이프라인으로 설계되었습니다.

1. Generative Alpha Discovery (Pre-Launcher & PA_launcher)
로직 생성의 이원화: LLM Agent가 두 가지 핵심 로직을 독립적으로 생성하고 최적화합니다.
- Price Action (Timing): 종목을 어떠한 로직과 시그널에 의해 사고팔지를 결정합니다.
- Asset Selection (Ranking): 매 시점마다 스코어링을 통해 무엇을 살지를 결정합니다.
- Potential Test : Price action algorithm과 Selection Algorithm의 여러 테스트를 바탕으로 휴리스틱하게 선정합니다. (자동화 구상중)
- Fast Backtest : 앞선 단계를 통과한 전략들에 대해 Equal Weight를 기반으로 백테스팅 성과를 기록합니다.
  
2. Risk-Aware Execution Simulation
- 리스크 관리 시스템: ATR 기반 손절 라인, 거래당 리스크 할당을 통한 포지션 사이징, 포트폴리오 리스크 캡, 최대 오픈 포지션 수 등을 통해 정밀한 리스크 관리를 통한 백테스팅 결과를 검증합니다.
- Mock Trading: 실거래 시스템에서 주문 넣는 부분만을 제외하여, 실제 백테스팅에서 보였던 전략 로직의 의도대로 작동하는지 한 번 더 검증합니다.
  
3. 현재 상황 및 향후 목표
- 현재 각 프로세스와 단계들을 구상하며 빌드하는 과정에 있습니다.
- 포텐셜 테스트 부분에서 휴리스틱하게 선정하는 과정을 조금 더 로직을 정비해서 자동화할 예정입니다.
- 리스크 기반 백테스팅의 경우, 여러 하이퍼 파라미터들을 시도해보는 중인데 이 부분에서도 최적화를 진행할 예정입니다.
- 최종 목표는 처음부터 실거래를 돌리는 과정까지 모든 과정을 자동화하는 것을 목표로 하고 있습니다.
