"""Camino de respaldo cuando el servicio de render no está: subtítulos karaoke ASS quemados con ffmpeg.

Sin banda, sin estilos por speaker y sin gancho: es el camino «de siempre» del proyecto viejo, pensado solo para
que un clip salga aunque el servicio de HyperFrames caiga. Un solo estilo, centrado en el corte entre el plano
corto y la escena completa."""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

from .ffmpeg_run import FfmpegError, progress_args, run_ffmpeg

BREAK_AFTER = re.compile(r"[.,?!;:…][\"'»”’)\]]*$")
MAX_WORDS, MAX_CHARS, MAX_GAP = 4, 22, 0.35
FONT = "DejaVu Sans"


class AssError(RuntimeError):
    pass


def group_phrases(words: list[dict], duration: float) -> list[list[dict]]:
    usable = [w for w in words if w["start"] < duration]
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for w in usable:
        prev = cur[-1] if cur else None
        chars = len(" ".join(x["text"] for x in cur))
        if prev and (
            len(cur) >= MAX_WORDS or w["start"] - prev["end"] > MAX_GAP or BREAK_AFTER.search(prev["text"])
            or w.get("speaker") != prev.get("speaker") or chars + 1 + len(w["text"]) > MAX_CHARS
        ):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _bgr(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper().replace("&H", "&H")


def _clean(text: str) -> str:
    return re.sub(r"[{}\\\n\r]", "", text).strip()


def build_ass(words: list[dict], *, duration: float, width: int = 1080, height: int = 1920,
              top_ratio: float = 0.5, accent: str = "#DA2E09") -> str:
    """ASS con una línea por frase y `\\kf` por palabra: las palabras barren de blanco al color de acento."""
    scale = width / 1080
    center_y = int(height * top_ratio) // 2 * 2
    lines = []
    for g in group_phrases(words, duration):
        start = g[0]["start"]
        end = min(duration, g[-1]["end"] + 0.25)
        text = " ".join(_clean(w["text"]).upper() for w in g)
        size = round(min(64, 0.9 * 1080 / max(1, len(text) * 0.7)) * scale)
        parts = " ".join("{\\kf%d}%s" % (max(1, round((w["end"] - w["start"]) * 100)), _clean(w["text"]).upper()) for w in g)
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Karaoke,,0,0,0,,"
                     f"{{\\an5\\pos({width // 2},{center_y})\\fs{max(24, size)}}}{parts}")
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,{FONT},{round(64 * scale)},{_bgr(accent)},&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{max(2, round(4 * scale))},1,5,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(lines) + "\n"


def _filter_escape(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def burn_subtitles(video: Path, words: list[dict], out_path: Path, *, duration: float, width: int, height: int,
                   top_ratio: float, draft: bool = False, ffmpeg: str = "ffmpeg",
                   on_progress: Callable[[float], None] | None = None,
                   cancel_check: Callable[[], None] | None = None) -> Path:
    """Quema los subtítulos en `video` (ya vertical) y escribe `out_path` de forma atómica."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ass = out_path.with_name(out_path.stem + ".ass")
    ass.write_text(build_ass(words, duration=duration, width=width, height=height, top_ratio=top_ratio), encoding="utf-8")
    part = out_path.with_name(out_path.stem + ".part" + out_path.suffix)
    quality = ["-crf", "28", "-preset", "veryfast"] if draft else ["-crf", "20", "-preset", "medium"]
    cmd = [*progress_args(ffmpeg), "-i", str(video), "-vf", f"ass='{_filter_escape(str(ass))}'",
           "-c:v", "libx264", *quality, "-pix_fmt", "yuv420p", "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
           "-movflags", "+faststart", "-c:a", "copy", str(part)]
    try:
        run_ffmpeg(cmd, duration=duration, cleanup=[part], on_progress=on_progress, cancel_check=cancel_check)
    except FfmpegError as exc:
        raise AssError(f"ffmpeg no pudo quemar los subtítulos: {exc}") from exc
    finally:
        ass.unlink(missing_ok=True)
    if not part.exists():
        raise AssError("ffmpeg no generó ningún fichero")
    os.replace(part, out_path)
    return out_path
