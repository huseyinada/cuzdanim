@echo off
chcp 65001 >nul
title Cuzdanim - Kisisel Finans
cd /d "%~dp0"

echo ==========================================
echo   Cuzdanim - Kisisel Finans Uygulamasi
echo ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [HATA] Python bulunamadi. https://www.python.org/downloads/ adresinden kurun
  echo        ve kurulumda "Add python.exe to PATH" secenegini isaretleyin.
  echo        (Python kurmak istemiyorsan: derle.bat ile Cuzdanim.exe uret.)
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Sanal ortam olusturuluyor...
  python -m venv .venv
  if errorlevel 1 ( echo [HATA] venv olusturulamadi. & pause & exit /b 1 )
)

echo [2/3] Paketler kontrol ediliyor / kuruluyor...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 ( echo [HATA] Paket kurulumu basarisiz. & pause & exit /b 1 )

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo       .env dosyasi olusturuldu (.env.example kopyalandi^).
)

echo [3/3] Uygulama baslatiliyor...
echo.
echo   PC'de ac:        http://localhost:8000
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
  for /f "tokens=* delims= " %%b in ("%%a") do echo   Telefondan ac:   http://%%b:8000   ^(ayni Wi-Fi^)
)
echo   API dokumani:    http://localhost:8000/docs
echo.
echo   Kod guncellenince sunucu kendini yeniden yukler (--reload).
echo   Durdurmak icin: Ctrl+C
echo ------------------------------------------
start "" "http://localhost:8000"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app
pause
