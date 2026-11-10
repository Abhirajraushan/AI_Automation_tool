@echo off
cd /d "%~dp0"
echo ========================================================
echo Starting 50 AUTO-APPLY on NAUKRI (Cybersecurity Profile)
echo ========================================================
echo Profile: Cybersecurity Developer / SOC / Security Engineer
echo Target: 50 Applications (ATS Score 60+)
echo ========================================================
python -m src.main run --site naukri --profile cybersecurity --auto --no-ask --limit 50 --retry
pause

