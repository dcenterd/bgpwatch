@echo off
rem Builds two things from the project folder (run:  packaging\build_windows.bat):
rem     dist\bgpwatch-onefile.exe   one self-contained file - double-click it
rem     dist\bgpwatch\bgpwatch.exe  the same app as a folder (starts faster, fewer antivirus warnings)
rem Needs Python 3.8+ (python.org installer, includes Tkinter) on PATH.
cd /d "%~dp0\.."
python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements.txt pyinstaller || exit /b 1

set COMMON=--noconfirm --windowed --icon packaging\bgpwatch.ico ^
  --add-data "bgpwatch\assets;bgpwatch\assets" ^
  --add-data "bgpwatch\*.py;bgpwatch" ^
  --add-data "main.py;." ^
  --collect-data ttkbootstrap ^
  --hidden-import pystray._win32

python -m PyInstaller %COMMON% --clean --name bgpwatch --workpath build\folder main.py || exit /b 1
python -m PyInstaller %COMMON% --onefile --name bgpwatch-onefile --workpath build\onefile main.py || exit /b 1
echo.
echo Done: dist\bgpwatch-onefile.exe  and  dist\bgpwatch\bgpwatch.exe
