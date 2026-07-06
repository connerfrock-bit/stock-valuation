@echo off
title Fair Value - data refresh
cd /d "C:\Users\conne\Desktop\stock valuation project\backend"
echo ============================================================
echo  Fair Value - full data refresh (union of Nasdaq-100 + S&P 500, ~25 min)
echo  1) EDGAR financials + prices   2) share-count cross-check
echo  3) betas    4) valuation engines (both universes)   5) forward ledgers
echo ============================================================
echo.

echo [1/5] Ingesting EDGAR financials + prices for the union (~15 min)...
python ingest_v1.py
if errorlevel 1 goto :fail
echo   (backfilling any names EDGAR throttled...)
python ingest_v1.py --resume
if errorlevel 1 goto :fail

echo.
echo [2/5] Cross-checking share counts vs Yahoo...
python sanity.py
if errorlevel 1 goto :fail

echo.
echo [3/5] Computing betas (~8 min)...
python betas.py
if errorlevel 1 goto :fail

echo.
echo [4/5] Running valuation engines for every universe...
python value.py all
if errorlevel 1 goto :fail

echo.
echo [5/6] Updating the forward paper-trading ledgers...
python ledger.py all
if errorlevel 1 goto :fail

echo.
echo [6/6] Refreshing the momentum factor study...
python momentum.py
python momentum.py sp500

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
