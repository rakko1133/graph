@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal
set "LOG=%~dp0log.txt"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem Use the dedicated venv python if present, otherwise the system python.
rem NOTE: console "python.exe" (NOT pythonw.exe) so errors are visible/logged.
set "PY=C:\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo ================================================== > "%LOG%"
echo  Launch log  %date% %time% >> "%LOG%"
echo  Folder : %CD% >> "%LOG%"
echo  Python : %PY% >> "%LOG%"
echo ================================================== >> "%LOG%"
"%PY%" --version >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo ---- output of graph_app.py ---- >> "%LOG%"

"%PY%" graph_app.py >> "%LOG%" 2>&1
set "EC=%ERRORLEVEL%"

echo. >> "%LOG%"
echo ---- exit code: %EC% ---- >> "%LOG%"

echo.
echo ===== launch log (also saved to log.txt) =====
type "%LOG%"
echo.
echo exit code: %EC%
echo.
echo This window stays open so you can read the error above.
echo The same text is saved in: "%LOG%"
pause
endlocal
