@echo off
rem Runs bgpwatch from source on Windows. The first run creates a .venv and installs the packages.
rem Needs Python 3.8+ from python.org (it includes Tkinter) - tick "Add python.exe to PATH".
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo First run: creating the virtual environment...
  python -m venv .venv || (echo Python was not found. Install it from https://www.python.org/downloads/ & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (pause & exit /b 1)
)
start "" ".venv\Scripts\pythonw.exe" main.py %*
