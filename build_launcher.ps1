$ErrorActionPreference = 'Stop'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
if (-not (Test-Path -LiteralPath $compiler)) { throw '未找到 .NET Framework C# 编译器。' }
Push-Location -LiteralPath $PSScriptRoot
try {
    & $compiler /nologo /target:winexe /platform:anycpu /optimize+ /win32manifest:WeChatBotLauncher.manifest '/resource:bot_launcher_helper.py,bot_launcher_helper.py' /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /out:WeChatBotLauncher.exe WeChatBotLauncher.cs
    if ($LASTEXITCODE -ne 0) { throw '编译失败。' }
    Write-Output '已生成 WeChatBotLauncher.exe，请放在 bot.py 同一目录运行。'
} finally { Pop-Location }
