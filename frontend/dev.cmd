@echo off
rem Dev-server launcher — makes Node visible to processes whose PATH predates the install.
rem cd to the LONG path (not %~dp0, which resolves 8.3 and trips Vite's fs.allow check).
set "PATH=C:\Program Files\nodejs;%PATH%"
cd /d "C:\Users\conne\Desktop\stock valuation project\frontend"
npm run dev
