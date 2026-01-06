#!/bin/bash

# run_auto.sh

echo "🚀 [Auto-Restart] 무한 루프 가동 시작..."

while true; do
    echo "----------------------------------------"
    echo "🐍 Python Process Starting (with taskpolicy)..."
    echo "----------------------------------------"
    
    # ★ 여기서 로그 저장(>) 부분은 뺍니다. 명령어만 깔끔하게 작성!
    # taskpolicy: macOS 효율 모드 실행
    # python -u: 로그 버퍼링 끄기 (실시간 기록)
    taskpolicy -c utility python -u ./src/pre_launcher.py
    
    EXIT_CODE=$?
    echo "⚠️  Process died with exit code: $EXIT_CODE"
    
    echo "🔄 3초 뒤 재시작합니다..."
    sleep 3
done