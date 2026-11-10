@echo off
cd /d "%~dp0"
echo ========================================================
echo Starting 50 AUTO-APPLY on LinkedIn (Backend Profile)
echo ========================================================
echo Note: Agar pehle se login nahi hai, to browser me LinkedIn
echo login karein aur fir yahan Enter dabayein.
echo ========================================================
python -m src.main run --site linkedin --profile backend --auto --no-ask --limit 50
pause

