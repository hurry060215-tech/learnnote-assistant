@echo off
setlocal
cd /d "%~dp0"

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo LearnNote requires Windows PowerShell.
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-learnnote.ps1" -OpenBrowser %*
if errorlevel 1 (
  echo.
  echo LearnNote did not start. The error above contains the next action.
  pause
  exit /b 1
)
endlocal
