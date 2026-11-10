@echo off
cd /d "%~dp0"
echo ========================================================
echo Closing Browser and Clearing Saved Browser Profiles/Logins...
echo ========================================================
taskkill /f /im msedge.exe >nul 2>&1
taskkill /f /im chrome.exe >nul 2>&1
timeout /t 2 >nul
if exist "data\chrome-profile" (
    rmdir /s /q "data\chrome-profile"
    echo Successfully removed all saved browser sessions and Google/Gmail logins!
) else (
    echo Already clean!
)
echo ========================================================
echo Ab browser me koi bhi Gmail ya Google account nahi bacha hai.
pause

