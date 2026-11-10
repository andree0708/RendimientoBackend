# Arranca el backend local en segundo plano como proceso independiente
# (no depende de ninguna terminal abierta).
# Uso:  . .\start-local.ps1     (desde RendimientoBackend)
# Parar: Stop-Process -Id (Get-Content backend-local.pid)

$ErrorActionPreference = 'Stop'

# La variable de entorno global DATABASE_URL apunta a un JDBC inválido para
# SQLAlchemy y tiene prioridad sobre el .env: hay que sobrescribirla.
$env:DATABASE_URL = 'sqlite:///./worksense.db'

$pidFile = Join-Path $PSScriptRoot 'backend-local.pid'
$logFile = Join-Path $PSScriptRoot 'backend-local.log'
$errFile = Join-Path $PSScriptRoot 'backend-local.err.log'

function Test-Port8000 {
    try {
        $c = New-Object Net.Sockets.TcpClient
        $r = $c.BeginConnect('127.0.0.1', 8000, $null, $null)
        $ok = $r.AsyncWaitHandle.WaitOne(1500)
        $c.Close()
        return $ok
    } catch { return $false }
}

if (Test-Port8000) {
    Write-Host 'El backend ya responde en http://localhost:8000 (nada que hacer).'
    exit 0
}

if (Test-Path $pidFile) {
    $old = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $old -Force
        Start-Sleep -Seconds 2
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$p = Start-Process -FilePath $python `
    -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--port', '8000') `
    -WorkingDirectory $PSScriptRoot -WindowStyle Hidden `
    -RedirectStandardOutput $logFile -RedirectStandardError $errFile `
    -PassThru
$p.Id | Out-File $pidFile -Encoding ascii
Write-Host "Backend arrancado (PID $($p.Id), log: backend-local.log). Verificando..."

$ok = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Port8000) { $ok = $true; break }
    if ($p.HasExited) { break }
}

if (-not $ok) {
    Write-Host 'ERROR: no responde en :8000. Últimas líneas del log:'
    Get-Content $logFile -Tail 15 -ErrorAction SilentlyContinue
    exit 1
}

try {
    $h = Invoke-RestMethod -Uri 'http://localhost:8000/health' -TimeoutSec 10
    Write-Host ("OK: backend en http://localhost:8000 (status={0})" -f $h.status)
} catch {
    Write-Host 'Puerto abierto pero /health falló. Revisa backend-local.log'
    exit 1
}
