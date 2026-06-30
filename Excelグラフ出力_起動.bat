@echo off
cd /d "%~dp0"
rem Excel グラフ出力ツール（GUI）を起動する。専用の仮想環境があれば使う。
set "PYW=C:\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" -m excel_chart.gui
