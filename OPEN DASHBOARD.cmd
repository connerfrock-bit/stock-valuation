@echo off
title Fair Value dashboard
set "PATH=C:\PROGRA~1\nodejs;%PATH%"

rem Already running? Just open the browser.
netstat -ano | findstr /r ":5173.*LISTENING" >nul 2>&1
if not errorlevel 1 (
  start "" http://localhost:5173
  exit /b 0
)

rem Otherwise start the dev server and open the browser once it's up.
cd /d "C:\Users\conne\Desktop\stock valuation project\frontend"
start /b "" cmd /c "timeout /t 3 /nobreak >nul & start "" http://localhost:5173"
echo Starting Fair Value dashboard... keep this window open while using it.
npm run dev
