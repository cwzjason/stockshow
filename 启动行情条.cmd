@echo off
cd /d "%~dp0"
if not exist "dist\WdcStockBar.exe" (
  echo Building WDC Stock Bar...
  dotnet publish src\StockBar -c Release -o dist --no-self-contained
  if errorlevel 1 (
    pause
    exit /b 1
  )
)
start "" "%~dp0dist\WdcStockBar.exe"
