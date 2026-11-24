@echo off
REM SFU Video Call Server Startup Script (AJAX Polling - No WebSockets)

echo ========================================
echo   SFU Video Call Server Setup
echo   Using AJAX Polling (cPanel Compatible)
echo ========================================
echo.

REM Check if Node.js is installed
where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Node.js is not installed or not in PATH
    echo Please install Node.js 18+ from https://nodejs.org/
    pause
    exit /b 1
)

REM Check Node.js version
for /f "delims=" %%i in ('node -v') do set NODE_VERSION=%%i
echo Found Node.js version: %NODE_VERSION%

REM Navigate to mediasoup server directory
cd /d "%~dp0mediasoup-server"

REM Check if node_modules exists
if not exist "node_modules" (
    echo.
    echo Installing dependencies...
    echo This may take a few minutes...
    npm install
    if %ERRORLEVEL% neq 0 (
        echo ERROR: Failed to install dependencies
        pause
        exit /b 1
    )
)

echo.
echo ========================================
echo   Starting Services
echo ========================================
echo.
echo Mediasoup SFU runs on port 3001 (HTTP API + AJAX polling)
echo Django runs on port 8000
echo.
echo Press Ctrl+C in each window to stop.
echo.

REM Start mediasoup server in background
echo Starting mediasoup SFU server on port 3001...
start "SFU Server (Port 3001)" cmd /k "npm start"

REM Wait for mediasoup to start
timeout /t 5 /nobreak >nul

REM Start Django server
echo Starting Django server on port 8000...
cd /d "%~dp0"
start "Django Server (Port 8000)" cmd /k "python manage.py runserver 127.0.0.1:8000"

echo.
echo ========================================
echo   Ready!
echo ========================================
echo.
echo Video Calls: http://127.0.0.1:8000/videocalls
echo.
pause
