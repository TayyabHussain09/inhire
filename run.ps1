$HostAddress = "127.0.0.1"
$Port = 8001

Write-Host "Starting inhire-interview at http://$HostAddress`:$Port"
Write-Host "If this port is busy, edit `$Port in run.ps1 to another value like 8002."

.\venv\Scripts\python.exe -m uvicorn app.main:app --host $HostAddress --port $Port --reload
