"""转码:探测、档位、ffmpeg 命令(DEV-PROMPTS-40 #342)。

**命令生成全是纯函数**(单测锁住):给定输入参数,出来的 ffmpeg 参数一个字不差。
真正跑 ffmpeg 的是 [run] —— 用 asyncio 子进程,不占事件循环;worker 和 inline 模式共用。

档位(D9):H.264 High + AAC 的 MP4,`+faststart`(元数据放文件头,边下边播),
关键帧 2 秒一个(拖进度条落点准)。竖屏按宽算档位 —— 1080×1920 的竖屏是「1080」档。
"""
import asyncio
import json
import logging
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("superz.media")

#: 档位:(名字, 短边像素, 视频码率上限 kbps)。不超过原片的短边;360 永远有
LADDER = ((1080, 1080, 5000), (720, 720, 2500), (480, 480, 1200), (360, 360, 800))
AUDIO_KBPS = 128
KEYFRAME_SECONDS = 2
#: 雪碧图:每张 10×10 格,每格 160 宽
SPRITE_COLS, SPRITE_ROWS, SPRITE_W = 10, 10, 160
#: 聊天视频不用转码的条件:已经是 H.264 + AAC(或无声)、短边 ≤ 1080、码率 ≤ 10Mbps
CHAT_MAX_SHORT = 1080
CHAT_MAX_BITRATE = 10_000_000


def have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@dataclass(frozen=True)
class Probe:
    duration_ms: int
    w: int
    h: int
    vcodec: str
    acodec: str
    bitrate: int
    rotation: int
    fmt: str

    @property
    def display_w(self) -> int:
        return self.h if self.rotation in (90, 270) else self.w

    @property
    def display_h(self) -> int:
        return self.w if self.rotation in (90, 270) else self.h

    @property
    def vertical(self) -> bool:
        return self.display_h > self.display_w

    @property
    def has_video(self) -> bool:
        return bool(self.vcodec)


def parse_probe(data: dict) -> Probe:
    """ffprobe -show_format -show_streams 的 JSON → Probe。纯函数。"""
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format") or {}
    dur = float(fmt.get("duration") or (v or {}).get("duration") or (a or {}).get("duration") or 0)
    rot = 0
    if v is not None:
        tags = v.get("tags") or {}
        try:
            rot = int(tags.get("rotate", 0)) % 360
        except (TypeError, ValueError):
            rot = 0
        for sd in v.get("side_data_list") or []:
            if "rotation" in sd:
                try:
                    rot = int(-float(sd["rotation"])) % 360
                except (TypeError, ValueError):
                    pass
    return Probe(
        duration_ms=int(round(dur * 1000)),
        w=int((v or {}).get("width") or 0), h=int((v or {}).get("height") or 0),
        vcodec=(v or {}).get("codec_name") or "", acodec=(a or {}).get("codec_name") or "",
        bitrate=int(fmt.get("bit_rate") or 0), rotation=rot,
        fmt=fmt.get("format_name") or "")


def ladder(p: Probe) -> list[tuple[int, int, int, int]]:
    """这个片子出哪些档:[(档名, 输出宽, 输出高, 码率 kbps)]。宽高都取偶数(H.264 要求)。"""
    w, h = p.display_w, p.display_h
    if w <= 0 or h <= 0:
        return []
    short = min(w, h)
    out = []
    for name, target_short, kbps in LADDER:
        if target_short > short and name != 360:
            continue
        s = min(target_short, short)
        if w <= h:      # 竖屏 / 方形:宽是短边
            ow, oh = s, round(h * s / w)
        else:
            ow, oh = round(w * s / h), s
        out.append((name, ow - ow % 2, oh - oh % 2, kbps))
    # 原片短边比 360 还小时,上面只会出一个 360 档(实际是原尺寸)
    return out


def rendition_args(src: str, dst: str, w: int, h: int, kbps: int, has_audio: bool) -> list[str]:
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
            "-map", "0:v:0", "-vf", f"scale={w}:{h}:flags=bicubic,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", "-crf", "23",
            "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k",
            "-force_key_frames", f"expr:gte(t,n_forced*{KEYFRAME_SECONDS})"]
    if has_audio:
        args += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-ac", "2"]
    else:
        args += ["-an"]
    return args + ["-movflags", "+faststart", dst]


def remux_args(src: str, dst: str) -> list[str]:
    """已经是 H.264/AAC 的只挪一下元数据位置(faststart),不重新编码。"""
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
            "-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy", "-movflags", "+faststart", dst]


def thumb_args(src: str, dst: str, at_seconds: float, width: int = 720) -> list[str]:
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at_seconds:.3f}",
            "-i", src, "-frames:v", "1", "-vf", f"scale='min({width},iw)':-2", "-q:v", "3", dst]


def sprite_interval_ms(duration_ms: int) -> int:
    """雪碧图每格间隔:整秒、至少 1 秒,总共不超过 400 格(4 张 10×10)。"""
    return max(1, math.ceil(duration_ms / 400 / 1000)) * 1000


def sprite_args(src: str, dst_pattern: str, interval_ms: int) -> list[str]:
    fps = 1000 / interval_ms
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
            "-vf", f"fps={fps:.6f},scale={SPRITE_W}:-2,tile={SPRITE_COLS}x{SPRITE_ROWS}",
            "-q:v", "5", dst_pattern]


def gif_args(src: str, dst: str) -> list[str]:
    """GIF → 无声 MP4 循环(D18)。宽高取偶数。"""
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
            "-movflags", "+faststart", "-pix_fmt", "yuv420p", "-an",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-crf", "26", dst]


def voice_args(src: str, dst: str) -> list[str]:
    """语音统一成 AAC 32kbps 单声道 m4a:安卓、网页、iOS 都能放。"""
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vn",
            "-ac", "1", "-ar", "24000", "-c:a", "aac", "-b:a", "32k", "-movflags", "+faststart",
            dst]


# ---------------- 音乐(DEV-PROMPTS-41 M4)----------------
#
# 两档:std 128k、hq 256k,都是 AAC-LC / 44.1kHz / 立体声的 m4a,`+faststart`(边下边播)。
# 响度统一到 −14 LUFS —— 不统一的话歌单里前一首震耳、后一首听不见,用户只能一首一首拧音量。
# 源码率低于 192k 的**不出 hq**:从 128k 的 mp3 转 256k 的 AAC 不会多出信息,只是白占一倍存储。

#: 档位名 → 目标码率 kbps
AUDIO_QUALITIES: dict[str, int] = {"std": 128, "hq": 256}
#: 统一响度(EBU R128 的 I 值,单位 LUFS)、真峰值上限 dBTP、响度范围 LU
AUDIO_LOUDNESS_I = -14
AUDIO_LOUDNESS_TP = -1.5
AUDIO_LOUDNESS_LRA = 11
AUDIO_SAMPLE_RATE = 44100
#: 源码率低于这个数就不出 hq(转上去也没有更多信息)
AUDIO_HQ_MIN_SOURCE_KBPS = 192


def audio_qualities(source_bitrate_bps: int) -> list[tuple[str, int]]:
    """这首歌出哪几档:[(档名, 码率 kbps)]。纯函数(单测锁住)。

    读不出源码率(bitrate = 0,常见于某些 wav / flac 容器)时**按无损算、两档都出** ——
    宁可多出一档,也不要把一首真无损的歌只留 128k。
    """
    out = [("std", AUDIO_QUALITIES["std"])]
    kbps = source_bitrate_bps // 1000
    if kbps == 0 or kbps >= AUDIO_HQ_MIN_SOURCE_KBPS:
        out.append(("hq", AUDIO_QUALITIES["hq"]))
    return out


def audio_rendition_args(src: str, dst: str, kbps: int) -> list[str]:
    """一档音乐的 ffmpeg 参数。纯函数(单测锁住,改一个字单测就红)。"""
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vn",
            "-af", f"loudnorm=I={AUDIO_LOUDNESS_I}:TP={AUDIO_LOUDNESS_TP}:"
                   f"LRA={AUDIO_LOUDNESS_LRA}",
            "-c:a", "aac", "-profile:a", "aac_low", "-b:a", f"{kbps}k",
            "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2",
            "-movflags", "+faststart", dst]


def pcm_args(src: str) -> list[str]:
    """解成 8kHz 单声道 16 位 PCM 输出到 stdout(算波形用)。"""
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", src, "-vn", "-ac", "1",
            "-ar", "8000", "-f", "s16le", "-"]


def waveform_from_pcm(pcm: bytes, buckets: int = 64) -> list[int]:
    """64 个 0–31 的峰值(和 TG 语音消息的波形一个意思)。纯函数。"""
    import array
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    n = len(samples)
    if n == 0:
        return [0] * buckets
    per = max(1, n // buckets)
    peaks = []
    for i in range(buckets):
        chunk = samples[i * per:(i + 1) * per] if i < buckets - 1 else samples[i * per:]
        peaks.append(max((abs(x) for x in chunk), default=0))
    top = max(peaks) or 1
    return [min(31, round(pk * 31 / top)) for pk in peaks]


#: 视频 / GIF 的分辨率上限:8K(长边 8192、总像素 3600 万)。再大的「视频」只可能是冲着解码内存来的 ——
#: 一帧 16K×16K 解开就是几百 MB,ffmpeg 还要缓几帧
VIDEO_MAX_SIDE = 8192
VIDEO_MAX_PIXELS = 36_000_000


def video_too_large(p: Probe) -> bool:
    w, h = p.display_w, p.display_h
    return max(w, h) > VIDEO_MAX_SIDE or w * h > VIDEO_MAX_PIXELS


def chat_video_needs_transcode(p: Probe) -> bool:
    if p.vcodec != "h264":
        return True
    if p.acodec and p.acodec != "aac":
        return True
    if min(p.display_w, p.display_h) > CHAT_MAX_SHORT:
        return True
    return p.bitrate > CHAT_MAX_BITRATE


class TranscodeError(RuntimeError):
    pass


async def run(args: list[str], *, timeout: float = 3600, capture: bool = False) -> bytes:
    """跑一个 ffmpeg / ffprobe。失败抛 TranscodeError(带 stderr 的最后几行)。"""
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise TranscodeError(f"{args[0]} 超时")
    if proc.returncode != 0:
        tail = (err or b"").decode(errors="ignore").strip().splitlines()[-3:]
        raise TranscodeError(f"{args[0]} 失败:{' / '.join(tail)[:280]}")
    return out or b""


async def probe(path: Path) -> Probe:
    out = await run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                     "-show_streams", str(path)], timeout=60, capture=True)
    try:
        return parse_probe(json.loads(out or b"{}"))
    except ValueError as e:
        raise TranscodeError("读不出这个文件的媒体信息") from e
