function Test-BridgeProcess {
    param($Process)
    if (-not $Process) { return $false }
    $pythonPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '.venv\Scripts\python.exe'))
    $launcherPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'pwm_local.py')).Replace('\', '/')
    $command = [string]$Process.CommandLine
    $pattern = '(?:^|[\s"])' + [regex]::Escape($launcherPath) + '(?=[\s"]|$)'
    return ($Process.ExecutablePath -eq $pythonPath -and $command.Replace('\', '/') -match $pattern)
}
