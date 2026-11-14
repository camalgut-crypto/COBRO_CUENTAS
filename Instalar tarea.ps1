# Crea la tarea programada "Cosechas vs Cobro - Actualizacion": al iniciar sesión deja corriendo el proceso que
# atiende el botón Actualizar y hace la carga diaria. Usa la carpeta donde está este archivo (OneDrive\Escritorio).
# Ejecutar en PowerShell:  powershell -ExecutionPolicy Bypass -File ".\Instalar tarea.ps1"
$raiz = $PSScriptRoot
$py = Join-Path $raiz ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $py)) { throw "No existe $py. Cree el entorno: py -3.12 -m venv .venv; .venv\Scripts\python.exe -m pip install pandas pyodbc keyring requests openpyxl" }
$accion = New-ScheduledTaskAction -Execute $py -Argument "worker\actualizar.py --escuchar" -WorkingDirectory $raiz
$disparo = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "Cosechas vs Cobro - Actualizacion" -Action $accion -Trigger $disparo -Settings $ajustes -Force | Out-Null
Start-ScheduledTask -TaskName "Cosechas vs Cobro - Actualizacion"
Write-Host "Tarea creada e iniciada: Cosechas vs Cobro - Actualizacion ($raiz)" -ForegroundColor Green
