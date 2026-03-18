@echo off
setlocal

set "OUTCSV=.\data\captures\monitor_lr_only.csv"
set "SECONDS=%~1"
if "%SECONDS%"=="" set "SECONDS=60"

set "BASE=%~2"

echo [1/2] Recording...
call .\rec_lr.cmd "%OUTCSV%" %SECONDS%
if errorlevel 1 exit /b %errorlevel%

echo.
echo [2/2] Generating JSON (no auto-retune)...
if "%BASE%"=="" (
  call .\gen_json.cmd "%OUTCSV%"
) else (
  call .\gen_json.cmd "%OUTCSV%" "%BASE%"
)

endlocal
