$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Bin = Join-Path $Root "tools\bin"
$Temp = Join-Path $env:TEMP ("rngn-media-tools-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $Bin,$Temp | Out-Null

function Download-File([string]$Url, [string]$Out) {
    Write-Host "Скачиваю: $Url" -ForegroundColor Cyan
    & curl.exe -L --fail --http1.1 --connect-timeout 20 --max-time 600 --retry 2 --retry-delay 2 --output $Out $Url
    if ($LASTEXITCODE -ne 0) { throw "Не удалось скачать $Url" }
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
    if (-not $ffmpeg -or -not $ffprobe) { throw "В архиве FFmpeg не найдены ffmpeg.exe/ffprobe.exe" }
    Copy-Item $ffmpeg.FullName (Join-Path $Bin "ffmpeg.exe") -Force
    Copy-Item $ffprobe.FullName (Join-Path $Bin "ffprobe.exe") -Force

    Write-Host ""; Write-Host "Инструменты готовы: $Bin" -ForegroundColor Green
}
finally {
    Remove-Item $Temp -Recurse -Force -ErrorAction SilentlyContinue
}
