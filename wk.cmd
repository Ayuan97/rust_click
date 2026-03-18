@echo off
setlocal

set "BASE=%~1"
if "%BASE%"=="" set "BASE=.\data\configs\BASE_TEMPLATE.json"

set "PARAMS=%~2"
if "%PARAMS%"=="" set "PARAMS=.\data\params\wk.json"

set "OUT=%~3"
if "%OUT%"=="" set "OUT=.\data\configs\wk.json"

python .\scripts\build_multi_weapon_config.py --in-json "%BASE%" --params "%PARAMS%" --out-json "%OUT%"
if errorlevel 1 exit /b %errorlevel%

echo.
echo Done. Import this file:
echo   %OUT%

endlocal
