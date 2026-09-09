# Kurulum / güncelleme scripti — VS Code klasörü açılınca otomatik çalışır (tasks.json).
# Idempotent: venv varsa atlar, paketler kuruluysa saniyeler içinde biter.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[1/2] Sanal ortam (.venv) olusturuluyor..." -ForegroundColor Cyan
    python -m venv .venv
}

Write-Host "[2/2] Paketler kontrol ediliyor / kuruluyor..." -ForegroundColor Cyan
& ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "      .env olusturuldu (.env.example kopyalandi)." -ForegroundColor Yellow
}

Write-Host "Hazir. Baslatmak icin: basla.bat  (veya VS Code: Terminal > Run Task > Calistir)" -ForegroundColor Green
