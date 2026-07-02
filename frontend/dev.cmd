@echo off
rem Dev-server launcher — makes Node visible to processes whose PATH predates the install.
rem Short 8.3 path (PROGRA~1) so no layer ever sees an unquoted space.
rem cd to the LONG project path (not %~dp0, which resolves 8.3 and trips Vite's fs.allow).
set "PATH=C:\PROGRA~1\nodejs;%PATH%"
cd /d "C:\Users\conne\Desktop\stock valuation project\frontend"
npm run dev
