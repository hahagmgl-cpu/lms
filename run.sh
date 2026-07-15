#!/bin/bash
# Smile Design Pro 실행 스크립트

set -e

echo "🦷 Smile Design Pro v2.0 시작 중..."

# 의존성 확인
if ! python3 -c "import PyQt6" 2>/dev/null; then
    echo "📦 PyQt6 설치 중..."
    pip install -r requirements.txt
fi

# 실행
python3 smile_overlay/main.py
