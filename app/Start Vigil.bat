@echo off
rem Launch Vigil with no console window, detached from this terminal.
rem Closing the window you started this from will NOT kill it.
setlocal

rem The "pythonw" on PATH is a Windows Store execution alias that `start`
rem cannot launch, so ask Python where the real pythonw.exe lives.
for /f "delims=" %%i in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do set "PYW=%%i"

if not exist "%PYW%" (
  echo Could not find pythonw.exe. Is Python installed and on PATH?
  pause
  exit /b 1
)

start "" "%PYW%" "%~dp0vigil_widget.py"
exit /b 0
