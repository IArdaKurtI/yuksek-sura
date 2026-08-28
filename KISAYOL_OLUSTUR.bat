@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0KISAYOL_OLUSTUR.ps1"
if errorlevel 1 (
  echo.
  echo Kisayol olusturulamadi.
  pause
  exit /b 1
)
echo.
echo YUKSEK SURA artik masaustunden baslatilabilir.
pause
exit /b 0
