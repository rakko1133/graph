@echo off
cd /d "%~dp0"
rem Launch the app with the dedicated virtual environment at C:\.venv
set "PYW=C:\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" graph_app.py
