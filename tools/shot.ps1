# Tangkapan layar tanpa Node: Edge headless dengan profil sekali pakai supaya
# halaman dan CSS tidak diambil dari cache profil sebelumnya.
param(
  [Parameter(Mandatory = $true)][string]$Path,
  [Parameter(Mandatory = $true)][string]$Out,
  [int]$Width = 1280,
  [int]$Height = 2600
)

$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $edge)) { $edge = "C:\Program Files\Microsoft\Edge\Application\msedge.exe" }

$profile = Join-Path $env:TEMP ("shot-" + [guid]::NewGuid().ToString("N"))
try {
  & $edge --headless=new --disable-gpu --no-first-run `
    --user-data-dir="$profile" `
    --window-size="$Width,$Height" --hide-scrollbars `
    --screenshot="$Out" "http://127.0.0.1:5000$Path" 2>$null | Out-Null
  Get-Item $Out | Select-Object Name, Length, LastWriteTime
}
finally {
  Remove-Item $profile -Recurse -Force -ErrorAction SilentlyContinue
}
