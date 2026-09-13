"""上传图片的分辨率上限要在解码之前判(#373 上传:超大分辨率图片)。

压得很小的超大图(纯色 PNG、1 bit)文件只有几十 KB,解开却要几百 MB 内存。
Image.open 只读文件头,尺寸是白拿的;判完再做 exif_transpose(它会把整张图解出来)。
"""
import pytest


def test_huge_image_rejected_before_decoding(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from PIL import Image, ImageOps

    from app.services import media

    p = tmp_path / "big.png"
    Image.new("1", (12000, 8000)).save(p)  # 9600 万像素,文件很小
    decoded = []
    monkeypatch.setattr(ImageOps, "exif_transpose", lambda im: decoded.append(1) or im)
    with pytest.raises(HTTPException) as e:
        media._image_process(p, "photo")
    assert e.value.status_code == 422 and "分辨率" in e.value.detail
    assert not decoded, "超限的图在判尺寸之前就被解码了"


def test_video_resolution_cap():
    """视频 / GIF 超过 8K 直接拒(ffprobe 只读头,拒在转码解码之前)。"""
    from app.services.transcode import Probe, video_too_large

    def probe(w, h, rot=0):
        return Probe(duration_ms=1000, w=w, h=h, vcodec="h264", acodec="aac", bitrate=1,
                     rotation=rot, fmt="mp4")

    assert not video_too_large(probe(3840, 2160))
    assert not video_too_large(probe(7680, 4320))
    assert video_too_large(probe(16384, 16384))
    assert video_too_large(probe(100, 9000)), "长边超了也拒(细长条)"
    assert video_too_large(probe(9000, 100, rot=90))
