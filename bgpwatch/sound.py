"""Alert sound: three beeps, played through the system audio (falls back to the Tk bell)."""
from __future__ import annotations

import math
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

RATE = 22050
PLAYERS = (("pw-play",), ("paplay",), ("aplay", "-q"))
_wav: Path | None = None


def _make_wav(beeps: int = 3, freq: int = 880, beep_s: float = 0.18, gap_s: float = 0.12) -> Path:
    path = Path(tempfile.gettempdir()) / "bgpwatch-alert.wav"
    frames = bytearray()
    fade = int(RATE * 0.01)
    n = int(RATE * beep_s)
    for _ in range(beeps):
        for i in range(n):
            env = min(1.0, i / fade, (n - i) / fade)
            frames += struct.pack("<h", int(14000 * env * math.sin(2 * math.pi * freq * i / RATE)))
        frames += b"\x00\x00" * int(RATE * gap_s)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return path


def play_alert() -> bool:
    """Start the 3-beep sound without blocking. False if no audio player is available."""
    global _wav
    try:
        if _wav is None or not _wav.exists():
            _wav = _make_wav()
        for cmd in PLAYERS:
            if shutil.which(cmd[0]):
                subprocess.Popen([*cmd, str(_wav)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
    except OSError:
        pass
    return False
