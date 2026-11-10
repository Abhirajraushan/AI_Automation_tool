@echo off
cd /d "%~dp0"
echo Starting Naukri Login...
python -m src.main login --site naukri
pause

