@echo off
rem Builds dist\bgpwatch\bgpwatch.exe (a folder you can zip). Run from the project folder:
rem     packaging\build_windows.bat
rem Needs Python 3.8+ (python.org installer, includes Tkinter) on PATH.
cd /d "%~dp0\.."
python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements.txt pyinstaller || exit /b 1
python -m PyInstaller --noconfirm --clean --windowed --name bgpwatch ^
  --icon packaging\bgpwatch.ico ^
  --add-data "bgpwatch\assets;bgpwatch\assets" ^
  --add-data "bgpwatch\*.py;bgpwatch" ^
  --add-data "main.py;." ^
  --collect-data ttkbootstrap ^
  --hidden-import pystray._win32 ^
  main.py || exit /b 1
echo.
echo Done: dist\bgpwatch\bgpwatch.exe
