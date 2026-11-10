@echo off
cd /d "%~dp0"
echo ========================================================
echo               APPLICATION HISTORY & REPORT
echo ========================================================
python -m src.main report
echo.
echo Complete history is also stored in: data\applications.csv
echo ========================================================
pause

