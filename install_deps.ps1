# Install all project dependencies into venv. Run once (or after pulling new deps).
Set-Location $PSScriptRoot
& "$PSScriptRoot\venv\Scripts\python.exe" -m pip install -r requirements.txt
