@echo off
cd /d "%~dp0"
echo ========================================================
echo Starting 100% AUTO-APPLY on NAUKRI (Backend Profile)
echo ========================================================
python -m src.main run --site naukri --profile backend --auto --no-ask --limit 20
pause

