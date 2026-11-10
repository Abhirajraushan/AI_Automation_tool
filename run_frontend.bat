@echo off
title Raushonix AI - Autonomous Placement Engine (by Abhiraj Raushan)
cd /d "%~dp0"
echo ======================================================================
echo           RAUSHONIX AI - AUTONOMOUS CAREER & PLACEMENT SUITE
echo                 Engineered by Abhiraj Raushan
echo ======================================================================
echo Initializing local dashboard service on http://localhost:5000...
echo Default browser will launch automatically.
echo.
echo Please keep this terminal active while using Raushonix AI.
echo ======================================================================
python -u run_web.py
pause
