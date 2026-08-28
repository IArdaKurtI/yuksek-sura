@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul
title Yuksek Sura

set "VENV_PY=.venv\Scripts\python.exe"

if exist "%VENV_PY%" (
  "%VENV_PY%" -c "import tkinter, litellm, pydantic, pydantic_settings, supreme_council.desktop" >nul 2>nul
  if not errorlevel 1 goto :READY
  echo Mevcut kurulum bozuk veya baska bir bilgisayardan kopyalanmis.
  echo Temiz bir ortam olusturuluyor...
  rmdir /s /q .venv
)

call :FIND_PYTHON
if not defined BASE_PY goto :NO_PYTHON

echo Kullanilan Python:
"%BASE_PY%" --version
echo.
echo Sanal ortam olusturuluyor...
"%BASE_PY%" -m venv .venv
if errorlevel 1 goto :FAILED

echo Gerekli kutuphaneler kuruluyor. Bu islem ilk acilista birkac dakika surebilir...
"%VENV_PY%" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel
if errorlevel 1 goto :FAILED
"%VENV_PY%" -m pip install --disable-pip-version-check .
if errorlevel 1 goto :FAILED

:READY
if /I "%~1"=="--check" (
  "%VENV_PY%" -m supreme_council.desktop --check
  exit /b !ERRORLEVEL!
)

if /I "%~1"=="--cli" goto :CLI

if not "%~1"=="" (
  echo Bilinmeyen secenek: %~1
  echo Arayuz icin BASLAT.bat, eski komut satiri icin BASLAT.bat --cli kullanin.
  pause
  exit /b 2
)

set "VENV_PYW=.venv\Scripts\pythonw.exe"
start "" "%VENV_PYW%" -m supreme_council.desktop
exit /b 0

:CLI
if not exist .env copy .env.example .env >nul
"%VENV_PY%" -m supreme_council.cli
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo Program hata kodu: %EXIT_CODE%
pause
exit /b %EXIT_CODE%

:FIND_PYTHON
set "BASE_PY="
for %%V in (3.13 3.12 3.11) do (
  if not defined BASE_PY for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)" 2^>nul') do call :CHECK_PYTHON "%%P"
)
for %%V in (313 312 311) do (
  if not defined BASE_PY if exist "%LocalAppData%\Programs\Python\Python%%V\python.exe" call :CHECK_PYTHON "%LocalAppData%\Programs\Python\Python%%V\python.exe"
)
if not defined BASE_PY for /f "delims=" %%P in ('where python 2^>nul') do call :CHECK_PYTHON "%%P"
exit /b 0

:CHECK_PYTHON
if not exist "%~1" exit /b 0
"%~1" -c "import sys, sysconfig; raise SystemExit(0 if sys.version_info >= (3, 11) and sysconfig.get_platform().startswith('win-') else 1)" >nul 2>nul
if not errorlevel 1 set "BASE_PY=%~1"
exit /b 0

:NO_PYTHON
echo.
echo Uyumlu Python bulunamadi.
echo python.org adresinden standart 64-bit Python 3.11 veya daha yenisini kurun.
echo Kurulumda "Add python.exe to PATH" secenegini isaretleyin.
echo MSYS/MinGW Python bu projenin ikili kutuphaneleriyle uyumlu degildir.
pause
exit /b 1

:FAILED
echo.
echo Kurulum tamamlanamadi. Yukaridaki ilk hata satirini kontrol edin.
pause
exit /b 1
