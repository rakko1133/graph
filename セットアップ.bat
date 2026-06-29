@echo off
cd /d "%~dp0"
echo ===========================================================
echo  Creating virtual environment at C:\.venv and installing
echo  dependencies. This may take a few minutes...
echo ===========================================================
set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m venv C:\.venv
if not exist "C:\.venv\Scripts\python.exe" (
  echo [ERROR] Failed to create the virtual environment.
  pause
  exit /b 1
)
C:\.venv\Scripts\python.exe -m pip install --upgrade pip
C:\.venv\Scripts\python.exe -m pip install -r requirements.txt spicelib
echo.
echo Done. Double-click 起動.bat to launch the app.
pause
