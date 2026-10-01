$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Tools = Join-Path $Root "tools"
$Bin = Join-Path $Tools "bin"
$Plugins = Join-Path $Tools "yt-dlp-plugins"
$ProviderDest = Join-Path $Tools "bgutil-ytdlp-pot-provider"
$Temp = Join-Path $env:TEMP ("rngn-media-tools-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $Bin,$Plugins,$Temp | Out-Null

function Download-File([string]$Url, [string]$Out) {
    Write-Host "Downloading: $Url" -ForegroundColor Cyan
    & curl.exe -L --fail --http1.1 --connect-timeout 20 --max-time 600 --retry 2 --retry-delay 2 --output $Out $Url
    if ($LASTEXITCODE -ne 0) { throw "Failed to download $Url" }
}

try {
    Download-File "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" (Join-Path $Bin "yt-dlp.exe")
    Download-File "https://github.com/gdl-org/builds/releases/latest/download/gallery-dl_windows.exe" (Join-Path $Bin "gallery-dl.exe")

    $DenoZip = Join-Path $Temp "deno.zip"
    Download-File "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" $DenoZip
    Expand-Archive -Path $DenoZip -DestinationPath $Temp -Force
    Copy-Item (Join-Path $Temp "deno.exe") (Join-Path $Bin "deno.exe") -Force

    $FfmpegZip = Join-Path $Temp "ffmpeg.zip"
    $FfmpegExtract = Join-Path $Temp "ffmpeg"
    Download-File "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" $FfmpegZip
    Expand-Archive -Path $FfmpegZip -DestinationPath $FfmpegExtract -Force
    $ffmpeg = Get-ChildItem $FfmpegExtract -Recurse -Filter ffmpeg.exe | Where-Object { $_.FullName -match '\\bin\\ffmpeg\.exe$' } | Select-Object -First 1
    $ffprobe = Get-ChildItem $FfmpegExtract -Recurse -Filter ffprobe.exe | Where-Object { $_.FullName -match '\\bin\\ffprobe\.exe$' } | Select-Object -First 1
    if (-not $ffmpeg -or -not $ffprobe) { throw "ffmpeg.exe/ffprobe.exe not found in FFmpeg archive" }
    Copy-Item $ffmpeg.FullName (Join-Path $Bin "ffmpeg.exe") -Force
    Copy-Item $ffprobe.FullName (Join-Path $Bin "ffprobe.exe") -Force

    $ProviderVersion = "2.0.0"
    $ProviderSource = Join-Path $Temp "bgutil-ytdlp-pot-provider"
    Write-Host "Preparing automatic YouTube PO Token provider $ProviderVersion..." -ForegroundColor Cyan
    & git clone --depth 1 --branch $ProviderVersion "https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git" $ProviderSource
    if ($LASTEXITCODE -ne 0) { throw "Failed to download bgutil-ytdlp-pot-provider" }

    Push-Location (Join-Path $ProviderSource "server")
    try {
        & (Join-Path $Bin "deno.exe") install --allow-scripts=npm:canvas --frozen
        if ($LASTEXITCODE -ne 0) { throw "Failed to install PO Token provider dependencies" }
    }
    finally {
        Pop-Location
    }

    Remove-Item $ProviderDest -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item $ProviderSource $ProviderDest -Recurse -Force
    Remove-Item (Join-Path $ProviderDest ".git") -Recurse -Force -ErrorAction SilentlyContinue

    Download-File "https://github.com/Brainicism/bgutil-ytdlp-pot-provider/releases/download/$ProviderVersion/bgutil-ytdlp-pot-provider.zip" (Join-Path $Plugins "bgutil-ytdlp-pot-provider.zip")

    Write-Host ""; Write-Host "Tools ready: $Bin" -ForegroundColor Green
    Write-Host "PO Token provider ready: $ProviderDest" -ForegroundColor Green
}
finally {
    Remove-Item $Temp -Recurse -Force -ErrorAction SilentlyContinue
}
