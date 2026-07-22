@echo off
cd /d "%~dp0"
rem Launch the SIMPLE single-file edition (graph_simple_onefile.py)
set "PYW=C:\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" graph_simple_onefile.py
