@echo off
title Fair Value - data refresh
cd /d "C:\Users\conne\Desktop\stock valuation project\backend"
echo ============================================================
echo  Fair Value - full data refresh (takes roughly 8-10 minutes)
echo  1) EDGAR financials + prices   2) share-count cross-check
echo  3) betas                      4) valuation engines
echo ============================================================
echo.

echo [1/4] Ingesting EDGAR financials + prices (~5 min)...
python ingest_v1.py
if errorlevel 1 goto :fail

echo.
echo [2/4] Cross-checking share counts vs Yahoo...
python sanity.py
if errorlevel 1 goto :fail

echo.
echo [3/4] Computing betas (~2 min)...
python betas.py
if errorlevel 1 goto :fail

echo.
echo [4/4] Running valuation engines...
python value.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  DONE - dashboard data refreshed.
echo  Open (or refresh) the dashboard to see the new numbers.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo ############################################################
echo  A step FAILED - the dashboard keeps its previous data.
echo  Scroll up for the error. Usually: no internet, or a source
echo  (EDGAR/Yahoo) temporarily blocking. Re-run in a few minutes.
echo ############################################################
pause
exit /b 1
