@echo off
setlocal

set "OUT=%~1"
if "%OUT%"=="" set "OUT=.\data\captures\monitor_lr_only.csv"

set "SECONDS=%~2"
if "%SECONDS%"=="" set "SECONDS=60"

if not exist ".\data\captures" mkdir ".\data\captures"

uv run --with hidapi python .\scripts\record_monitor_csv.py --out "%OUT%" --wait-buttons --only-while-buttons --only 0x00010030 0x00010031 0x00090001 0x00090002 --no-dedupe --seconds %SECONDS%

endlocal
