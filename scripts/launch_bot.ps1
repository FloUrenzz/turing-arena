param([switch]$Diagnostics)
$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'Turing Arena v3'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$repoDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoDirectory
Write-Host 'Turing Arena v3'
Write-Host 'Введите вопрос и нажмите Enter'
$botArguments = @('-B', '-X', 'utf8', 'main.py', '--chat', '--corpus', 'data/dialogue-combined-5350-v2.sqlite3')
if ($Diagnostics) { $botArguments += '--diagnostics' }
& python @botArguments
