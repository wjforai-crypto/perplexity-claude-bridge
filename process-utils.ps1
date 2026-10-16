function Test-BridgeProcess {
    param($Process)
    if (-not $Process) { return $false }
    $pythonPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '.venv\Scripts\python.exe'))
    $allowedInterpreters = @($pythonPath)
    # Windows venv python.exe can launch a child in the base installation.
    # Still require the exact launcher belonging to this checkout below.
    $venvConfig = Join-Path $PSScriptRoot '.venv\pyvenv.cfg'
    if (Test-Path -LiteralPath $venvConfig) {
        $homeLine = Get-Content -LiteralPath $venvConfig | Where-Object { $_ -match '^home\s*=\s*' } | Select-Object -First 1
        if ($homeLine) {
            $baseDirectory = ($homeLine -replace '^home\s*=\s*', '').Trim()
            if ([IO.Path]::IsPathFullyQualified($baseDirectory)) {
                $allowedInterpreters += [IO.Path]::GetFullPath((Join-Path $baseDirectory 'python.exe'))
            }
        }
    }
    $launcherPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'pwm_local.py')).Replace('\', '/')
    $command = [string]$Process.CommandLine
    $pattern = '(?:^|[\s"])' + [regex]::Escape($launcherPath) + '(?=[\s"]|$)'
    return ($Process.ExecutablePath -in $allowedInterpreters -and $command.Replace('\', '/') -match $pattern)
}
