# Mirrors PurpleThunder's D: to BBB's D:\PT_D. Later runs copy only what changed.
# A mirror also deletes files from the backup when they're deleted here. It isn't version history.
$logDir = 'D:\Repos\gpu-second-life\backup_logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("backup_pt_d_" + (Get-Date -Format 'yyyy-MM-dd_HHmmss') + '.log')
robocopy D:\ \\192.168.2.217\D\PT_D /MIR /XJ /MT:8 /R:1 /W:5 /COPY:DAT /DCOPY:T /NP /NFL /NDL `
    /XD '$RECYCLE.BIN' 'System Volume Information' /XF pagefile.sys hiberfil.sys swapfile.sys /LOG:$log | Out-Null
$code = $LASTEXITCODE
"robocopy code: $code (0 to 7 can mean success; 8 or higher means failures)"
Select-String -Path $log -Pattern '^\s+(Dirs|Files|Bytes|Times) :\s+\S|Ended :' | ForEach-Object { $_.Line }
"error lines: " + @(Select-String -Path $log -Pattern ' ERROR \d').Count
"log: $log"
