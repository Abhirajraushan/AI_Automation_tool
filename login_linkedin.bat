@echo off
cd /d "%~dp0"
echo Starting LinkedIn Login...
python -m src.main login --site linkedin
pause

