# Read-only hardware and storage check for Noodlecart. Changes nothing.
$ErrorActionPreference = 'SilentlyContinue'
'=== OS'
Get-CimInstance Win32_OperatingSystem | ForEach-Object { "$($_.Caption) build $($_.BuildNumber), RAM $([math]::Round($_.TotalVisibleMemorySize/1MB)) GB" }
'=== BOARD'
Get-CimInstance Win32_BaseBoard | ForEach-Object { "$($_.Manufacturer) $($_.Product)" }
'=== GPU'
Get-CimInstance Win32_VideoController | ForEach-Object { "$($_.Name), driver $($_.DriverVersion)" }
nvidia-smi --query-gpu=index,name,memory.total,driver_version,temperature.gpu,fan.speed,ecc.mode.current --format=csv
'=== DISKS'
Get-PhysicalDisk | ForEach-Object { "$($_.FriendlyName), $($_.BusType), $($_.MediaType), $([math]::Round($_.Size/1GB)) GB, $($_.HealthStatus)" }
'=== VOLUMES'
Get-Volume | Where-Object DriveLetter | ForEach-Object { "$($_.DriveLetter): $($_.FileSystemLabel), $([math]::Round($_.Size/1GB)) GB, $([math]::Round($_.SizeRemaining/1GB)) GB free" }
'=== OLD SERVICE DATA'
Get-PSDrive -PSProvider FileSystem | ForEach-Object { Get-ChildItem -Path $_.Root -Directory -Depth 2 -Force | Where-Object Name -Match 'qdrant|jazz|embed' | ForEach-Object { $_.FullName } }
'=== TOP FOLDERS'
Get-PSDrive -PSProvider FileSystem | ForEach-Object { Get-ChildItem -Path $_.Root -Directory | ForEach-Object { $_.FullName } }
'=== DONE'
