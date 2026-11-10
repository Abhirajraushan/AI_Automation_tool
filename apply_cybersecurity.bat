@echo off
cd /d "%~dp0"
echo ========================================================
echo Starting 100% AUTO-APPLY on LinkedIn + Naukri (Cybersecurity Profile)
echo ========================================================
python -m src.main run --site all --profile cybersecurity --auto --no-ask --limit 20
pause
