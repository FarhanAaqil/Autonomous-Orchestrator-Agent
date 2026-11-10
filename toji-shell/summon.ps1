$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try { npm start } finally { Pop-Location }
