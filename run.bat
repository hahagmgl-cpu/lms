@echo off
REM Smile Design Pro 실행 스크립트 (Windows)

echo 🦷 Smile Design Pro v2.0 시작 중...

REM 의존성 확인
python -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo 📦 PyQt6 설치 중...
    pip install -r requirements.txt
)

REM 실행
python smile_overlay/main.py
pause
