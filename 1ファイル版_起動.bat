@echo off
cd /d "%~dp0"
rem Launch the single-file edition. Builds it first if it is missing
rem (the single-file build is a generated artifact and is not in git).
set "PY=C:\.venv\Scripts\python.exe"
set "PYW=C:\.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=python"
if not exist "%PYW%" set "PYW=pythonw"
if not exist "graph_onefile.py" (
  echo Building graph_onefile.py ...
  "%PY%" tools\build_onefile.py
)
if not exist "graph_onefile.py" (
  echo Build failed. Run the setup bat first.
  pause
  exit /b 1
)
start "" "%PYW%" graph_onefile.py
