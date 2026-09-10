@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv
  .venv\Scripts\python.exe -m pip install -e ".[hardware]"
)
.venv\Scripts\python.exe main.py
if errorlevel 1 pause
