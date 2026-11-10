@echo off
cd /d "%~dp0"
echo ========================================================
echo Starting 100% AUTO-APPLY on NAUKRI (Cybersecurity Profile)
echo ========================================================
python -m src.main run --site naukri --profile cybersecurity --auto --no-ask --limit 20
pause

