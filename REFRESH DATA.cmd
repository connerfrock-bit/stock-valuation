@echo off
title Fair Value - data refresh
rem /auto = headless (scheduled task): skip the pauses so the run can end itself
if /I "%~1"=="/auto" set FV_AUTO=1
cd /d "C:\Users\conne\Desktop\stock valuation project\backend"
echo ============================================================
echo  Fair Value - full data refresh (union of all configured universes)
echo  0) bulk EDGAR download + filers scan   1) financials + prices
echo  2) share cross-check   3) betas   3b) daily prices (chart)   4) engines
echo  5) ledgers   5b) calibration   6) momentum   7) S&P 1500 data-quality gate
echo  8) publish refreshed data to GitHub (auto runs only)
echo ============================================================
echo.

echo [0/7] Refreshing bulk EDGAR zips (conditional) + filers scan...
echo   (one ~2.9GB nightly download replaces ~500 throttled per-ticker calls;
echo    If-Modified-Since skips it when SEC has not rebuilt since last run)
python bulk.py download
if errorlevel 1 goto :fail
python bulk.py scan
if errorlevel 1 goto :fail

echo.
echo [1/7] Ingesting EDGAR financials + prices for the union (~2 min from the zip)...
python ingest_v1.py
if errorlevel 1 goto :fail
echo   (backfilling any names EDGAR throttled / newer than the nightly zip...)
python ingest_v1.py --resume
if errorlevel 1 goto :fail

echo.
echo [2/7] Cross-checking share counts vs Yahoo...
python sanity.py
if errorlevel 1 goto :fail

echo.
echo [3/7] Computing betas (~8 min)...
python betas.py
if errorlevel 1 goto :fail

echo.
echo [3b/7] Fetching daily prices for the deep-dive price chart (non-fatal)...
echo   (adds one Yahoo pass; bakes prices_^<universe^>.json. A failure here leaves the
echo    chart on its last data and never blocks the valuation publish below.)
python prices_daily.py

echo.
echo [4/7] Running valuation engines for every universe...
python value.py all
if errorlevel 1 goto :fail

echo.
echo [5/7] Updating the forward paper-trading ledgers...
python ledger.py all
if errorlevel 1 goto :fail

echo.
echo [5b/7] Rebuilding the cross-sectional calibration report (non-fatal)...
echo   (rank IC of predicted upside vs realized forward return, across EVERY name in
echo    each frozen snapshot — the ledger's 18-name basket is too small to read alone.
echo    Non-fatal so a calibration bug can never block the valuation publish below.)
python calibration.py all

echo.
echo [6/7] Refreshing the momentum factor study...
python momentum.py
python momentum.py sp500

echo.
echo [7/7] Data-quality dry run (S&P 1500 coverage gate for universe expansion)...
python dataquality.py sp1500

echo.
echo [8/8] Publishing refreshed data to GitHub (auto runs only)...
if not defined FV_AUTO (
  echo   Manual run - skipping publish. Commit ^& push yourself when ready.
  goto :done
)
cd /d "C:\Users\conne\Desktop\stock valuation project"
git add frontend/public
git diff --cached --quiet
if not errorlevel 1 (
  echo   No data changes since last publish - nothing to push.
  goto :done
)
git commit -m "Daily data refresh %DATE% %TIME%"
if errorlevel 1 goto :pushfail
git push origin main
if errorlevel 1 goto :pushfail
echo   Published - the live dashboard updates in about a minute.
goto :done

:pushfail
echo   WARNING: data refreshed and committed locally, but the push failed
echo   (usually a transient network/auth blip). The commit is safe; the next
echo   day's run will push it along with the new data. No data is lost.

:done
echo.
echo ============================================================
echo  DONE - dashboard data refreshed.
echo  Open (or refresh) the dashboard to see the new numbers.
echo ============================================================
if not defined FV_AUTO pause
exit /b 0

:fail
echo.
echo ############################################################
echo  A step FAILED - the dashboard keeps its previous data.
echo  Scroll up for the error. Usually: no internet, or a source
echo  (EDGAR/Yahoo) temporarily blocking. Re-run in a few minutes.
echo ############################################################
if not defined FV_AUTO pause
exit /b 1
