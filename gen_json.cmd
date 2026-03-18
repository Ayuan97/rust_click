@echo off
setlocal

set "CSV=%~1"
if "%CSV%"=="" set "CSV=.\data\captures\monitor_lr_only.csv"

set "BASE=%~2"
set "MODE=%~3"
set "BASE_STABLE=.\data\configs\BASE_TEMPLATE.json"
set "PARAMS=.\data\params\ak_tune_params.json"
set "IMPORTJSON=.\data\configs\IMPORT_THIS_TO_HID.json"

if "%BASE%"=="" if exist "%BASE_STABLE%" set "BASE=%BASE_STABLE%"
if "%BASE%"=="" if exist ".\data\configs\current_export.json" set "BASE=.\data\configs\current_export.json"
if "%BASE%"=="" if exist "%IMPORTJSON%" set "BASE=%IMPORTJSON%"

if "%BASE%"=="" (
  echo [Missing base json]
  echo Provide base json as arg2:
  echo   .\gen_json.cmd .\data\captures\monitor_lr_only.csv .\data\configs\your_base.json
  exit /b 1
)

if not exist "%BASE_STABLE%" copy /Y "%BASE%" "%BASE_STABLE%" >nul
if exist "%BASE_STABLE%" set "BASE=%BASE_STABLE%"

if /I "%MODE%"=="--retune" (
  echo [1/2] Retune from CSV: %CSV%
  python .\scripts\retune_from_csv.py --exact --csv "%CSV%" --params "%PARAMS%" --out "%PARAMS%"
  if errorlevel 1 goto :eof
) else (
  echo [1/2] Skip auto-retune. Keep existing params:
  echo       %PARAMS%
)

echo [2/2] Build HID config from: %BASE%
python .\scripts\apply_ak_tune.py --in-json "%BASE%" --params "%PARAMS%" --out-json "%IMPORTJSON%"
if errorlevel 1 goto :eof

echo.
echo Done. Import this file:
echo   %IMPORTJSON%

echo Base template locked at:
echo   %BASE_STABLE%
echo (Delete BASE_TEMPLATE.json once if you want to reset base.)
echo.
echo Tip:
echo   Add --retune as arg3 if you want one-shot auto-retune from CSV.

endlocal
