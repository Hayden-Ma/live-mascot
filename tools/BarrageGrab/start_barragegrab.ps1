$env:DOTNET_ROOT = "E:\project\stream\tools\dotnet-x86"
${env:DOTNET_ROOT(x86)} = $env:DOTNET_ROOT
Start-Process -FilePath "E:\project\stream\tools\BarrageGrab\BarrageGrab.exe" -WorkingDirectory "E:\project\stream\tools\BarrageGrab"
