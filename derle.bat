@echo off
title Cuzdanim - EXE derleme
cd /d "%~dp0"

echo ==========================================
echo   Cuzdanim.exe derleniyor (PyInstaller)
echo ==========================================

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Sanal ortam olusturuluyor...
  python -m venv .venv || ( echo [HATA] venv olusturulamadi. & pause & exit /b 1 )
)

echo [2/4] Paketler + PyInstaller kuruluyor...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller || ( echo [HATA] Paket kurulumu basarisiz. & pause & exit /b 1 )

echo [3/4] Ikonlar uretiliyor...
".venv\Scripts\python.exe" -m app.tools.make_icons || ( echo [HATA] Ikon uretilemedi. & pause & exit /b 1 )

echo [4/4] Derleniyor (2-4 dakika)...
rem (--clean kullanilmiyor: OneDrive/Defender onbellek klasorunu kilitleyip derlemeyi bozabiliyor)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm cuzdanim.spec || ( echo [HATA] Derleme basarisiz. & pause & exit /b 1 )

rem Final adi Turkce karakterli: Cuzdanim.exe -> C(u:)zdan(i)m.exe  (karakterler kod ile yaziliyor, kodlama sorunu olmasin)
powershell -NoProfile -Command "$n = 'C' + [char]0xFC + 'zdan' + [char]0x131 + 'm.exe'; Copy-Item -Force 'dist\Cuzdanim.exe' (Join-Path 'dist' $n); Write-Host ('Hazir: dist\' + $n)"

echo.
echo   dist\ klasorundeki .exe dosyasini istedigin klasore kopyala ve cift tikla.
echo   Veritabani, yedekler ve ayarlar .exe'nin yanindaki klasorde olusur.
echo.
pause
