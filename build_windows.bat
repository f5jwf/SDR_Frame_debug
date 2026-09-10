@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m pip install pyinstaller
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --windowed --name SDRFrameDebug --collect-all pyqtgraph --collect-all adi --hidden-import rtlsdr main.py
if errorlevel 1 pause
