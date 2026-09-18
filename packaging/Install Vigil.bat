@echo off
title Install Vigil
setlocal

rem Vigil installs to your local disk, NOT to wherever this folder happens to
rem sit. Running from OneDrive or a USB stick made the agent hook 3.5x slower.
set "TARGET=%USERPROFILE%\.vigil\app"
set "SRC=%~dp0"

echo.
echo   Vigil - ambient status for your AI coding agents
echo   ================================================
echo.

rem ---------------------------------------------------------------------------
rem SAFETY: copy only OUR files by name. An earlier version used
rem   xcopy "%%~dp0*"
rem which, if you extract the zip loose into a folder like Downloads instead of
rem into its own subfolder, copies that ENTIRE folder. Never wildcard the
rem source directory in an installer.
rem ---------------------------------------------------------------------------
if not exist "%SRC%Vigil.exe" goto :notourfolder
if not exist "%SRC%_internal\" goto :notourfolder
if not exist "%SRC%hook\vigil-hook.exe" goto :notourfolder

echo   Installing to: %TARGET%
echo.

taskkill /IM Vigil.exe /F >nul 2>&1
taskkill /IM vigil-hook.exe /F >nul 2>&1
timeout /t 1 /nobreak >nul

if exist "%TARGET%" rmdir /s /q "%TARGET%" >nul 2>&1
mkdir "%TARGET%" >nul 2>&1
mkdir "%TARGET%\hook" >nul 2>&1

echo   Copying files...
copy  /y "%SRC%Vigil.exe"   "%TARGET%\"          >nul || goto :copyfail
copy  /y "%SRC%README.txt"  "%TARGET%\"          >nul
copy  /y "%SRC%Uninstall Vigil.bat" "%TARGET%\"  >nul
xcopy /E /I /Q /Y "%SRC%_internal" "%TARGET%\_internal" >nul || goto :copyfail
xcopy /E /I /Q /Y "%SRC%hook"      "%TARGET%\hook"      >nul || goto :copyfail

if not exist "%TARGET%\hook\vigil-hook.exe" goto :copyfail

echo   Connecting to Claude Code...
"%TARGET%\Vigil.exe" --install

echo   Starting Vigil...
start "" "%TARGET%\Vigil.exe"

echo.
echo   Done.
echo.
echo   Vigil is running - look bottom-right, an inch above the taskbar.
echo   Right-click the dot, or the tray icon by the clock, for settings.
echo.
echo   IMPORTANT: restart Claude Code. Hooks only load when a session starts,
echo   so any window you already have open will not report yet.
echo.
pause
exit /b 0

:notourfolder
echo   ERROR: this does not look like the Vigil folder.
echo.
echo   Expected to find Vigil.exe, _internal\ and hook\ next to this installer,
echo   in: %SRC%
echo.
echo   If you extracted the zip loosely into Downloads or Desktop, put the Vigil
echo   files in their own folder and run this again from inside it.
echo.
pause
exit /b 1

:copyfail
echo.
echo   ERROR: copy failed. Nothing was installed.
echo.
pause
exit /b 1
