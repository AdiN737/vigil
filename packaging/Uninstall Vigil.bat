@echo off
title Uninstall Vigil
setlocal
set "TARGET=%USERPROFILE%\.vigil\app"
echo.
echo   Removing Vigil...
echo.
taskkill /IM Vigil.exe /F >nul 2>&1
taskkill /IM vigil-hook.exe /F >nul 2>&1
timeout /t 1 /nobreak >nul
if exist "%TARGET%\Vigil.exe" (
  "%TARGET%\Vigil.exe" --uninstall
) else (
  echo   Vigil.exe not found; removing what is left.
)
timeout /t 1 /nobreak >nul
if exist "%USERPROFILE%\.vigil" rmdir /s /q "%USERPROFILE%\.vigil" >nul 2>&1
echo.
echo   Vigil removed: hooks unregistered, autostart cleared, data deleted.
echo   Your Claude Code settings.json was backed up before each change.
echo.
pause
