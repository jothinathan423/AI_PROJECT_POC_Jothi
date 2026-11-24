@echo off
echo Stopping any running uvicorn on port 8001...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8001 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo Starting backend with hot-reload on port 8001...
cd /d "%~dp0backend"
..\venv\Scripts\uvicorn main:app --port 8001 --reload
