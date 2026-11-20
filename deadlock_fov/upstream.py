"""Download config files from the OptiLock GitHub repository."""

from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request

from .config import GITHUB_BRANCH, GITHUB_OWNER, GITHUB_REPO, Preset

RAW_URL = "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
USER_AGENT = "DeadlockFovTool/1.0"
TIMEOUT_SECONDS = 25

VERSION_RE = re.compile(r"ver\.\s*([0-9]+(?:\.[0-9]+)*)")


class UpstreamError(RuntimeError):
    """Raised when the config could not be downloaded."""


def raw_url(preset: Preset, filename: str) -> str:
    path = "/".join((preset.folder, filename))
    return RAW_URL.format(
        owner=GITHUB_OWNER,
        repo=GITHUB_REPO,
        branch=GITHUB_BRANCH,
        path=urllib.parse.quote(path),
    )


def fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpstreamError(
                f"Could not download the config: the file was not found on the server (404).\n\n{url}"
            ) from exc
        raise UpstreamError(
            f"Could not download the config: the server returned HTTP {exc.code}.\n\n{url}"
        ) from exc
    except urllib.error.URLError as exc:
        raise UpstreamError(
            f"Could not download the config: no connection to the server ({exc.reason})."
        ) from exc
    except TimeoutError as exc:
        raise UpstreamError("Could not download the config: the download timed out.") from exc


def decode(data: bytes) -> str:
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def fetch_text(url: str) -> str:
    return decode(fetch(url))


def sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def config_version(text: str) -> str:
    """Pull the ``ver. 6.0`` marker out of the OptiLock banner."""
    match = VERSION_RE.search(text[:4000])
    return match.group(1) if match else ""
