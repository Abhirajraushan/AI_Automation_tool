@echo off
cd /d "%~dp0"
echo ========================================================
echo Starting 100% AUTO-APPLY: NAUKRI + LINKEDIN
echo ========================================================
echo.
echo [1/2] Launching NAUKRI Auto-Apply (Backend Developer)...
python -m src.main run --site naukri --profile backend --auto --no-ask --limit 15
echo.
echo [2/2] Launching LINKEDIN Auto-Apply (Backend Developer)...
python -m src.main run --site linkedin --profile backend --auto --no-ask --limit 15
echo.
echo ========================================================
echo ALL DONE! Both Naukri and LinkedIn have completed.
echo ========================================================
pause
