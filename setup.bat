@echo off
title Raushonix AI - 1-Click Automated Setup
cd /d "%~dp0"
echo ======================================================================
echo           RAUSHONIX AI — 1-CLICK AUTOMATED SETUP WIZARD
echo ======================================================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in your Windows PATH!
    echo Please install Python 3.10 or higher from https://www.python.org/downloads/
    echo IMPORTANT: Make sure to check the box "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo [1/3] Python detected successfully.
echo [2/3] Installing required libraries (this takes about 1-2 minutes)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies. Please check your internet connection.
    pause
    exit /b 1
)

echo [3/3] Setting up automated browser engine (Playwright Chromium)...
python -m playwright install chromium
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install Playwright browser engine.
    pause
    exit /b 1
)

echo.
echo ======================================================================
echo   SUCCESS! Raushonix AI is fully configured and ready to use!
echo   Launching the Web Dashboard at http://localhost:5000...
echo ======================================================================
echo.
timeout /t 3 >nul
start "" "start_ui.bat"

