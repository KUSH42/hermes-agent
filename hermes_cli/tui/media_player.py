"""media_player.py — mpv-based inline audio/video player support for the TUI."""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import parse_qs, urlparse

# ── URL detection patterns ─────────────────────────────────────────────────────
_AUDIO_EXT_RE = re.compile(
    r'https?://\S+\.(?:mp3|wav|ogg|flac|aac|m4a|opus)(?:\?[^\s]*)?', re.I)
_VIDEO_EXT_RE = re.compile(
    r'https?://\S+\.(?:mp4|mkv|webm|mov)(?:\?[^\s]*)?', re.I)
_YOUTUBE_RE   = re.compile(
    r'https?://(?:www\.)?(?:youtube\.com/watch\?[^\s]*v=|youtu\.be/)[\w\-]+'
    r'(?:[&\?][^\s]*)?')


def _short_url(url: str) -> str:
    """Return last path segment or YouTube ID. Max 24 chars."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "v" in qs:
        return qs["v"][0][:24]
    if "youtu.be" in parsed.netloc:
        return parsed.path.lstrip("/")[:24]
    seg = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return (seg[:21] + "…") if len(seg) > 24 else seg


def _resolve_youtube_url(url: str) -> str | None:
    """Resolve YouTube URL to direct stream URL via yt-dlp -g. Returns None on failure."""
    if not shutil.which("yt-dlp"):
        return None
    try:
        result = subprocess.run(
            ["yt-dlp", "-g", "--no-playlist", url],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode == 0:
            line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
            return line or None
    except Exception:
        pass
    return None


# ── Config ─────────────────────────────────────────────────────────────────────

@dataclass
class InlineMediaCfg:
    enabled: bool = False
    audio: bool = True
    video_thumbs: bool = True
    show_timeline: bool = True
    timeline_auto_s: int = 30
    player: str = "mpv"
    player_extra_args: list = field(default_factory=list)
    youtube: bool = True
    max_concurrent: int = 2


def _inline_media_config() -> InlineMediaCfg:
    try:
        from hermes_cli.config import read_raw_config
        d = read_raw_config().get("display", {}).get("inline_media", {})
    except Exception:
        d = {}
    return InlineMediaCfg(
        enabled=bool(d.get("enabled", False)),
        audio=bool(d.get("audio", True)),
        video_thumbs=bool(d.get("video_thumbs", True)),
        show_timeline=bool(d.get("show_timeline", True)),
        timeline_auto_s=int(d.get("timeline_auto_s", 30)),
        player=str(d.get("player", "mpv")),
        player_extra_args=list(d.get("player_extra_args", [])),
        youtube=bool(d.get("youtube", True)),
        max_concurrent=int(d.get("max_concurrent", 2)),
    )


# ── MpvController ──────────────────────────────────────────────────────────────

class MpvController:
    """Manages one mpv subprocess + UNIX IPC socket."""

    def __init__(
        self,
        url: str,
        kind: str,
        cfg: InlineMediaCfg,
        resolved_url: str | None = None,
    ) -> None:
        self._url = url
        self._resolved_url = resolved_url or url
        self._kind = kind
        self._cfg = cfg
        self._ipc_path = f"/tmp/hermes-mpv-{uuid.uuid4().hex[:8]}.sock"
        self._proc: subprocess.Popen | None = None  # type: ignore[type-arg]
        self._ipc_started = False

    def start(self) -> None:
        player = self._cfg.player or "mpv"
        args = [
            player,
            self._resolved_url,
            f"--input-ipc-server={self._ipc_path}",
            "--really-quiet",
            "--term-status-line=no",
        ]
        if self._kind == "audio":
            args.append("--no-video")
        args.extend(self._cfg.player_extra_args)
        try:
            self._proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._ipc_started = False
        except Exception:
            self._proc = None

    def stop(self) -> None:
        self._ipc_send(["quit"])
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

    def pause(self) -> None:
        self._ipc_send(["set_property", "pause", True])

    def resume(self) -> None:
        self._ipc_send(["set_property", "pause", False])

    def seek(self, pos_s: float) -> None:
        self._ipc_send(["seek", pos_s, "absolute"])

    def get_position(self) -> float | None:
        resp = self._ipc_send(["get_property", "time-pos"])
        if resp is not None and isinstance(resp.get("data"), (int, float)):
            return float(resp["data"])
        return None

    def get_duration(self) -> float | None:
        resp = self._ipc_send(["get_property", "duration"])
        if resp is not None and isinstance(resp.get("data"), (int, float)):
            return float(resp["data"])
        return None

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _ipc_send(self, cmd: list) -> dict | None:  # type: ignore[type-arg]
        """Send a JSON command via UNIX socket. Returns parsed response or None."""
        deadline = time.monotonic() + (1.0 if not self._ipc_started else 0.0)
        while True:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(0.2)
                    sock.connect(self._ipc_path)
                    payload = json.dumps({"command": cmd}) + "\n"
                    sock.sendall(payload.encode())
                    data = b""
                    while b"\n" not in data:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    self._ipc_started = True
                    return json.loads(data.split(b"\n")[0])
            except FileNotFoundError:
                if time.monotonic() < deadline:
                    time.sleep(0.1)
                    continue
                return None
            except Exception:
                return None


# ── MpvPoller ──────────────────────────────────────────────────────────────────

class MpvPoller:
    """Daemon thread polling mpv position/duration at 4 Hz."""

    POLL_HZ = 4

    def __init__(
        self,
        ctrl: MpvController,
        on_tick: Callable[[float, float], None],
        on_end: Callable[[], None],
    ) -> None:
        self._ctrl = ctrl
        self._on_tick = on_tick
        self._on_end = on_end
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if not self._ctrl.is_alive():
                self._on_end()
                return
            pos = self._ctrl.get_position()
            dur = self._ctrl.get_duration()
            if pos is not None and dur is not None:
                self._on_tick(pos, dur)
            self._stop_event.wait(1.0 / self.POLL_HZ)


# ── Thumbnail helpers ──────────────────────────────────────────────────────────

def _fetch_youtube_thumbnail(url: str) -> str | None:
    """Fetch YouTube thumbnail to a temp file. Returns path or None."""
    try:
        from urllib.request import urlretrieve
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "v" in qs:
            vid_id = qs["v"][0]
        elif "youtu.be" in parsed.netloc:
            vid_id = parsed.path.lstrip("/").split("?")[0]
        else:
            return None
        thumb_url = f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"
        fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
        import os
        os.close(fd)
        urlretrieve(thumb_url, tmp_path)
        return tmp_path
    except Exception:
        return None


def _extract_video_thumbnail(path_or_url: str) -> str | None:
    """Extract first frame from video via ffmpeg. Returns path or None."""
    if not shutil.which("ffmpeg"):
        return None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
        import os
        os.close(fd)
        result = subprocess.run(
            [
                "ffmpeg", "-i", path_or_url,
                "-vframes", "1",
                "-ss", "00:00:01",
                tmp_path, "-y", "-loglevel", "quiet",
            ],
            capture_output=True, timeout=15,
        )
        if result.returncode == 0:
            return tmp_path
    except Exception:
        pass
    return None
