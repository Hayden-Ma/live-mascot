# Auto-reconnecting SSH tunnel for the GPU server (multi-port local forwarding).
# ServerAliveInterval keeps the connection from being dropped by NAT/VPN idle timeouts;
# the outer loop reconnects after sleep, Wi-Fi switch or network failures.

# SSH 主机/端口/账号从项目根目录 .env 读取（.env 已被 gitignore）。
$envFile = Join-Path $PSScriptRoot '..\.env'
if (Test-Path $envFile) {
  Get-Content -Path $envFile -Encoding UTF8 | ForEach-Object {
    if ($_ -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
      $name = $matches[1]
      $value = $matches[2].Trim()
      if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
        $value = $value.Substring(1, $value.Length - 2)
      }
      if (-not (Test-Path "env:$name")) { Set-Item "env:$name" $value }
    }
  }
}
if (-not $env:REMOTE_HOST -or -not $env:REMOTE_PORT -or -not $env:REMOTE_USER) {
  throw '请在项目根目录 .env 中配置 REMOTE_HOST / REMOTE_PORT / REMOTE_USER'
}

$ssh = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$key = Join-Path $env:USERPROFILE '.ssh\id_ed25519_tunnel'
$remote = '{0}@{1}' -f $env:REMOTE_USER, $env:REMOTE_HOST
$remotePort = $env:REMOTE_PORT

$forwards = @(
  '9876:127.0.0.1:9876',
  '10911:127.0.0.1:10911',
  '11011:127.0.0.1:11011',
  '11111:127.0.0.1:11111',
  '11211:127.0.0.1:11211',
  '8080:127.0.0.1:8080',
  '2181:127.0.0.1:2181',
  '2182:127.0.0.1:2182',
  '2183:127.0.0.1:2183',
  '13306:127.0.0.1:3306',
  '6379:127.0.0.1:6379',
  '9200:127.0.0.1:9200',
  '11434:127.0.0.1:11434',
  '8081:127.0.0.1:8081',
  '45100:127.0.0.1:45100'
)

$sshArgs = @(
  '-N',
  '-i', $key,
  '-p', $remotePort,
  '-o', 'BatchMode=yes',
  '-o', 'ServerAliveInterval=30',
  '-o', 'ServerAliveCountMax=3',
  '-o', 'TCPKeepAlive=yes',
  '-o', 'ExitOnForwardFailure=yes',
  '-o', 'ConnectTimeout=15'
)
foreach ($f in $forwards) { $sshArgs += @('-L', $f) }
$sshArgs += $remote

while ($true) {
  Write-Host ('[{0}] connecting to {1} ...' -f (Get-Date -Format 'HH:mm:ss'), $remote)
  & $ssh @sshArgs
  Write-Host ('[{0}] disconnected (exit {1}), retry in 5s' -f (Get-Date -Format 'HH:mm:ss'), $LASTEXITCODE)
  Start-Sleep -Seconds 5
}
