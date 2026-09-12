"""转码的纯函数:探测结果解析、档位、雪碧图间隔、波形、Range 解析(DEV-PROMPTS-40 #341 #342)。"""
import array
import math

from app.routers.media import parse_range
from app.services.media import resolve_kind, sniff
from app.services.transcode import (Probe, chat_video_needs_transcode, ladder, parse_probe,
                                    rendition_args, sprite_interval_ms, waveform_from_pcm)


def probe(w, h, vcodec="h264", acodec="aac", bitrate=2_000_000, rotation=0):
    return Probe(duration_ms=10_000, w=w, h=h, vcodec=vcodec, acodec=acodec, bitrate=bitrate,
                 rotation=rotation, fmt="mov,mp4")


def test_parse_probe_rotation_and_cover_art():
    data = {"format": {"duration": "12.5", "bit_rate": "3000000", "format_name": "mov,mp4"},
            "streams": [
                {"codec_type": "video", "codec_name": "mjpeg", "width": 300, "height": 300,
                 "disposition": {"attached_pic": 1}},
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
                 "side_data_list": [{"rotation": -90}]},
                {"codec_type": "audio", "codec_name": "aac"}]}
    p = parse_probe(data)
    assert (p.w, p.h, p.rotation) == (1920, 1080, 90), "封面图不是视频流;旋转从 side_data 读"
    assert (p.display_w, p.display_h) == (1080, 1920) and p.vertical
    assert p.duration_ms == 12500 and p.vcodec == "h264" and p.acodec == "aac"


def test_ladder_landscape_portrait_and_small():
    assert [r[:3] for r in ladder(probe(1920, 1080))] == [
        (1080, 1920, 1080), (720, 1280, 720), (480, 852, 480), (360, 640, 360)]
    assert [r[:3] for r in ladder(probe(1080, 1920))] == [
        (1080, 1080, 1920), (720, 720, 1280), (480, 480, 852), (360, 360, 640)], "竖屏按宽算"
    assert [r[:3] for r in ladder(probe(1280, 720))][0] == (720, 1280, 720), "不超过原片"
    small = ladder(probe(320, 240))
    assert len(small) == 1 and small[0][1:3] == (320, 240), "比 360 还小:只出原尺寸一档"
    assert all(r[1] % 2 == 0 and r[2] % 2 == 0 for r in ladder(probe(1001, 777))), "宽高取偶数"


def test_rendition_args_have_faststart_and_keyframes():
    args = rendition_args("in.mov", "out.mp4", 1280, 720, 2500, has_audio=False)
    assert "+faststart" in args and "-an" in args and "libx264" in args
    assert any("n_forced*2" in a for a in args), "关键帧 2 秒一个"


def test_chat_video_transcode_decision():
    assert not chat_video_needs_transcode(probe(1280, 720))
    assert chat_video_needs_transcode(probe(1280, 720, vcodec="vp9"))
    assert chat_video_needs_transcode(probe(1280, 720, acodec="opus"))
    assert chat_video_needs_transcode(probe(3840, 2160))
    assert chat_video_needs_transcode(probe(1280, 720, bitrate=20_000_000))
    assert not chat_video_needs_transcode(probe(1280, 720, acodec="")), "无声视频不用转"


def test_sprite_interval():
    assert sprite_interval_ms(60_000) == 1000
    assert sprite_interval_ms(1_800_000) == 5000
    assert 1_800_000 // sprite_interval_ms(1_800_000) <= 400


def test_waveform():
    rising = array.array("h", [int(30000 * i / 8000 * math.sin(i)) for i in range(8000)])
    w = waveform_from_pcm(rising.tobytes())
    assert len(w) == 64 and max(w) == 31 and w[0] < w[-1]
    assert waveform_from_pcm(b"") == [0] * 64


def test_sniff_and_kind():
    assert sniff(b"\xff\xd8\xff\xe0" + b"0" * 60)[0] == "image"
    assert sniff(b"\x00\x00\x00\x18ftypM4A " + b"0" * 48)[0] == "audio"
    assert sniff(b"\x00\x00\x00\x18ftypisom" + b"0" * 48)[0] == "video"
    assert sniff(b"MZ\x90\x00" + b"0" * 60)[0] == "file"
    assert resolve_kind("photo", "file") == "file", "说是图片、其实不是:当文件"
    assert resolve_kind("photo", "gif") == "gif"
    assert resolve_kind("voice", "audio") == "voice"
    assert resolve_kind("video", "audio") == "file"


def test_parse_range():
    assert parse_range(None, 100) is None
    assert parse_range("bytes=0-9", 100) == (0, 9)
    assert parse_range("bytes=90-", 100) == (90, 99)
    assert parse_range("bytes=-10", 100) == (90, 99)
    assert parse_range("bytes=50-500", 100) == (50, 99)
    assert parse_range("bytes=200-", 100) == (-1, -1)
    assert parse_range("bytes=0-1,5-6", 100) is None, "多段按整份返回"
