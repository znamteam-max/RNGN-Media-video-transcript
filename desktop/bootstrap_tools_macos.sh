#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$ROOT/tools"
BIN="$TOOLS/bin"
LIB="$TOOLS/lib"
PLUGINS="$TOOLS/yt-dlp-plugins"
PROVIDER_DEST="$TOOLS/bgutil-ytdlp-pot-provider"
TMP="$(mktemp -d -t rngn-media-tools.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$BIN" "$LIB" "$PLUGINS"

download() {
  local url="$1"
  local out="$2"
  echo "Downloading: $url"
  curl -L --fail --retry 2 --retry-delay 2 --connect-timeout 20 --max-time 600 -o "$out" "$url"
}

download "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos" "$BIN/yt-dlp"
download "https://github.com/gdl-org/builds/releases/latest/download/gallery-dl_macos" "$BIN/gallery-dl"

ARCH="$(uname -m)"
if [[ "$ARCH" == "arm64" ]]; then
  DENO_ASSET="deno-aarch64-apple-darwin.zip"
elif [[ "$ARCH" == "x86_64" ]]; then
  DENO_ASSET="deno-x86_64-apple-darwin.zip"
else
  echo "Unsupported macOS architecture: $ARCH" >&2
  exit 1
fi

download "https://github.com/denoland/deno/releases/latest/download/$DENO_ASSET" "$TMP/deno.zip"
ditto -x -k "$TMP/deno.zip" "$TMP/deno"
cp "$TMP/deno/deno" "$BIN/deno"

FFMPEG="$(command -v ffmpeg || true)"
FFPROBE="$(command -v ffprobe || true)"
if [[ -z "$FFMPEG" || -z "$FFPROBE" ]]; then
  echo "ffmpeg/ffprobe not found. Install them with Homebrew before running this script." >&2
  exit 1
fi

cp "$FFMPEG" "$BIN/ffmpeg"
cp "$FFPROBE" "$BIN/ffprobe"

chmod +x "$BIN/yt-dlp" "$BIN/gallery-dl" "$BIN/deno" "$BIN/ffmpeg" "$BIN/ffprobe"

if command -v dylibbundler >/dev/null 2>&1; then
  dylibbundler -od -b -x "$BIN/ffmpeg" -d "$LIB" -p "@executable_path/../lib"
  dylibbundler -od -b -x "$BIN/ffprobe" -d "$LIB" -p "@executable_path/../lib"
else
  echo "dylibbundler not found. Install it with: brew install dylibbundler" >&2
  exit 1
fi

PROVIDER_VERSION="2.0.0"
PROVIDER_SOURCE="$TMP/bgutil-ytdlp-pot-provider"
echo "Preparing automatic YouTube PO Token provider $PROVIDER_VERSION..."
git clone --depth 1 --branch "$PROVIDER_VERSION"   https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "$PROVIDER_SOURCE"

(
  cd "$PROVIDER_SOURCE/server"
  "$BIN/deno" install --allow-scripts=npm:canvas --frozen
)

rm -rf "$PROVIDER_DEST"
cp -R "$PROVIDER_SOURCE" "$PROVIDER_DEST"
rm -rf "$PROVIDER_DEST/.git"

download   "https://github.com/Brainicism/bgutil-ytdlp-pot-provider/releases/download/$PROVIDER_VERSION/bgutil-ytdlp-pot-provider.zip"   "$PLUGINS/bgutil-ytdlp-pot-provider.zip"

echo
echo "macOS tools ready:"
file "$BIN/yt-dlp" || true
file "$BIN/gallery-dl" || true
file "$BIN/deno" || true
file "$BIN/ffmpeg" || true
file "$BIN/ffprobe" || true

echo "PO Token provider:"
test -f "$PLUGINS/bgutil-ytdlp-pot-provider.zip"
test -d "$PROVIDER_DEST/server/node_modules"
