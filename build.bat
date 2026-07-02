@echo off
REM Build file .exe bang PyInstaller (chay tren Windows)
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --windowed --name HSMT-Analyzer main.py
echo.
echo Xong! File exe nam trong thu muc dist\HSMT-Analyzer.exe
pause
