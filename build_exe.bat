@echo off
cd /d "%~dp0"
echo Building BatteryMonitor.exe...

pyinstaller --onefile --noconsole --name "BatteryMonitor" ^
    --icon "charge.png" ^
    --add-data "HarmonyOS_Sans_SC_Bold.ttf;." ^
    --add-data "charge.wav;." ^
    --add-data "charge.png;." ^
    --hidden-import psutil ^
    --hidden-import wmi ^
    --hidden-import ctypes ^
    --hidden-import ctypes.wintypes ^
    --hidden-import winreg ^
    --hidden-import win32com ^
    --hidden-import PyQt6.QtMultimedia ^
    --clean ^
    main.py

echo Done! Output in dist\BatteryMonitor.exe
pause
