"""Keeps yt-dlp / gallery-dl fresh (sites change often) and checks for a new RNGN Media."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import APP_VERSION, GITHUB_REPO
from .procs import creation_flags
from .tools import exe, read_versions, resolve_tools, user_tools_dir, version_key, write_versions

USER_AGENT = f"RNGN-Media/{APP_VERSION}"
TOOL_SOURCES = {
    "yt-dlp": {
        "repo": "yt-dlp/yt-dlp",
        "asset": "yt-dlp.exe" if os.name == "nt" else "yt-dlp_macos",
        "sums": "SHA2-256SUMS",
        "every": 24 * 3600,
    },
    "gallery-dl": {
        "repo": "gdl-org/builds",
        "asset": "gallery-dl_windows.exe" if os.name == "nt" else "gallery-dl_macos",
        "sums": "SHA2-256SUMS",
        "every": 7 * 24 * 3600,
    },
}


def _get_json(url: str, timeout: float = 15) -> dict | list:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _download(url: str, target: Path, timeout: float = 120) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = target.with_suffix(target.suffix + ".download")
    with urllib.request.urlopen(request, timeout=timeout) as response, tmp.open("wb") as output:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            output.write(chunk)
    tmp.replace(target)


def tool_version(path: Path) -> str:
    try:
        result = subprocess.run(
            [str(path), "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=40,
            creationflags=creation_flags(),
        )
        return (result.stdout or "").strip().splitlines()[0] if result.stdout.strip() else ""
    except Exception:
        return ""


def _bundled_version(name: str, path: Path, cache: dict) -> str:
    """yt-dlp: real --version. gallery-dl nightly builds: file date (their tags are dates)."""
    stamp = f"{path}|{path.stat().st_mtime_ns}|{path.stat().st_size}"
    if cache.get("bundled_stamp") == stamp and cache.get("bundled"):
        return str(cache["bundled"])
    if name == "gallery-dl":
        value = time.strftime("%Y.%m.%d", time.localtime(path.stat().st_mtime))
    else:
        value = tool_version(path)
    cache["bundled_stamp"] = stamp
    cache["bundled"] = value
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_tools(*, force: bool = False, log=lambda _s: None) -> dict:
    """Download newer yt-dlp / gallery-dl into the user folder. Returns per-tool status."""
    if sys.platform not in {"win32", "darwin"}:
        return {}
    bundled = resolve_tools(allow_updates=False)
    versions = read_versions()
    result: dict = {}
    for name, source in TOOL_SOURCES.items():
        entry = versions.setdefault(name, {})
        path = bundled.yt_dlp if name == "yt-dlp" else bundled.gallery_dl
        try:
            entry["bundled"] = _bundled_version(name, path, entry)
            if not force and time.time() - float(entry.get("checked") or 0) < source["every"]:
                result[name] = {**entry, "status": "fresh"}
                continue
            release = _get_json(f"https://api.github.com/repos/{source['repo']}/releases/latest")
            latest = str(release.get("tag_name") or "")
            entry["checked"] = time.time()
            entry["latest"] = latest
            current = max(entry.get("bundled") or "", entry.get("user") or "", key=version_key)
            if version_key(latest) <= version_key(current):
                result[name] = {**entry, "status": "up-to-date"}
                continue
            assets = {item.get("name"): item.get("browser_download_url") for item in release.get("assets") or []}
            url = assets.get(source["asset"])
            if not url:
                result[name] = {**entry, "status": "no-asset"}
                continue
            target = user_tools_dir() / exe(name)
            fresh = target.with_name(target.name + ".new")
            log(f"Обновляю {name} до {latest}…")
            _download(url, fresh)
            sums_url = assets.get(source["sums"])
            if sums_url:
                request = urllib.request.Request(sums_url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=20) as response:
                    sums = response.read().decode("utf-8", errors="replace")
                expected = next(
                    (line.split()[0].lower() for line in sums.splitlines()
                     if line.strip().endswith(source["asset"])),
                    "",
                )
                if expected and expected != _sha256(fresh):
                    fresh.unlink(missing_ok=True)
                    result[name] = {**entry, "status": "checksum-mismatch"}
                    continue
            if os.name != "nt":
                fresh.chmod(0o755)
            if not tool_version(fresh):
                fresh.unlink(missing_ok=True)
                result[name] = {**entry, "status": "broken-download"}
                continue
            fresh.replace(target)
            entry["user"] = latest
            result[name] = {**entry, "status": "updated"}
            log(f"{name} обновлён до {latest}")
        except Exception as exc:
            result[name] = {**entry, "status": "error", "error": str(exc)}
    write_versions(versions)
    return result


def check_app_update() -> dict | None:
    """Newest published desktop release for this OS, if newer than the running version."""
    prefix = "macos-v" if sys.platform == "darwin" else "desktop-v"
    releases = _get_json(f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=20")
    best: dict | None = None
    for release in releases if isinstance(releases, list) else []:
        tag = str(release.get("tag_name") or "")
        if not tag.startswith(prefix) or release.get("draft") or release.get("prerelease"):
            continue
        version = tag[len(prefix):]
        if best is None or version_key(version) > version_key(best["version"]):
            best = {"version": version, "url": release.get("html_url") or "", "notes": release.get("body") or ""}
    if best and version_key(best["version"]) > version_key(APP_VERSION):
        return best
    return None
