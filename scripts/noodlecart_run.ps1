# Sends noodlecart_check.ps1 to Noodlecart over SSH, using this PC's SSH key.
$script = Get-Content -Raw -Path (Join-Path $PSScriptRoot 'noodlecart_check.ps1')
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
ssh Admin@192.168.2.51 "powershell -NoProfile -EncodedCommand $encoded"
