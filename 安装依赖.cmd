@echo off
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto error
.venv\Scripts\python.exe -m pip install -r bridge\requirements.txt
if errorlevel 1 goto error
echo Ready. Launch Stock Bar. No broker login or OpenD required.
pause
exit /b 0
:error
echo Setup failed. Check Python installation and network access.
pause
exit /b 1
