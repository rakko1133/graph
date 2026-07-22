@echo off
cd /d "%~dp0"
rem Launch the SIMPLE edition (same app, fewer controls shown at first)
set "PYW=C:\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" graph_app_simple.py
