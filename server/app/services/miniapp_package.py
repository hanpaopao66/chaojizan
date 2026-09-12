"""小程序托管包:校验、落存储、托管出口的返回头(#322,DEV-PROMPTS-39 §5.6)。

## 校验规则(每条在 tests/unit/test_miniapp_package.py 里有一个用例)

- zip;应用 ≤ 10 MB、小游戏 ≤ 30 MB(压缩后),单文件 ≤ 5 MB,文件数 ≤ 1000;
- 解压总量 ≤ 3 倍压缩量且 ≤ 90 MB(防 zip 炸弹 —— 看的是 zip 目录里声明的大小,
  解压时再按实际读出的字节数复核一遍,声明造假的包在读的时候被截住);
- 根目录必须有 index.html 和 superz.json;
- 扩展名白名单;拒绝符号链接、绝对路径、反斜杠、`..`(zip slip)、重复路径;
- superz.json:sdk 必须是 "2",kind 必须和应用一致,orientation ∈ portrait/landscape/any,
  background_color 是 #RRGGBB,spa_fallback 是布尔。

## 为什么对象只写一次

审核看的就是上线的那一份(I4)。键 `miniapps/<appid>/<version_id>/<path>`,
版本 id 是新行的主键,不会复用 —— 同一个键不可能被写第二次。
"""
import hashlib
import io
import json
import re
import stat
import zipfile
from dataclasses import dataclass, field

MAX_ZIP = {"app": 10 * 1024 * 1024, "game": 30 * 1024 * 1024}
MAX_FILE = 5 * 1024 * 1024
MAX_FILES = 1000
MAX_RATIO = 3
MAX_TOTAL = 90 * 1024 * 1024

CONTENT_TYPES = {
    "html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8",
    "mjs": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8",
    "json": "application/json", "txt": "text/plain; charset=utf-8",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "webp": "image/webp", "svg": "image/svg+xml", "ico": "image/x-icon",
    "woff": "font/woff", "woff2": "font/woff2", "ttf": "font/ttf", "otf": "font/otf",
    "mp3": "audio/mpeg", "ogg": "audio/ogg", "wav": "audio/wav", "m4a": "audio/mp4",
    "webm": "video/webm", "mp4": "video/mp4", "wasm": "application/wasm",
    "map": "application/json",
}
ORIENTATIONS = ("portrait", "landscape", "any")
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_EXTERNAL_SCRIPT = re.compile(r"<script[^>]+src\s*=\s*[\"']?\s*(https?:)?//", re.I)
_EXTERNAL_STYLE = re.compile(r"<link[^>]+href\s*=\s*[\"']?\s*(https?:)?//", re.I)


@dataclass
class PackageReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)          # superz.json 解析结果
    files: dict[str, dict] = field(default_factory=dict)  # path -> {size, sha256, type}
    sha256: str = ""
    size: int = 0
    blobs: dict[str, bytes] = field(default_factory=dict, repr=False)

    def fail(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)

    def public(self) -> dict:
        """给开发者看的校验报告(不含文件内容)。"""
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings,
                "sha256": self.sha256, "size": self.size, "file_count": len(self.files),
                "manifest": self.manifest}


def content_type(path: str) -> str | None:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return CONTENT_TYPES.get(ext)


def _bad_path(name: str) -> str | None:
    if "\\" in name:
        return "路径里不能有反斜杠"
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return "不能是绝对路径"
    parts = name.split("/")
    if any(p in ("..", ".") for p in parts):
        return "路径里不能有 .. 或 ."
    if any(p == "" for p in parts):
        return "路径里不能有空段"
    if any(p.startswith(".") for p in parts) and not name.startswith(".well-known/"):
        return "不能包含隐藏文件"
    return None


def validate_package(data: bytes, *, kind: str) -> PackageReport:
    rep = PackageReport(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    limit = MAX_ZIP.get(kind, MAX_ZIP["app"])
    if len(data) > limit:
        rep.fail(f"压缩包 {len(data) // 1024} KB,超过{'小游戏' if kind == 'game' else '应用'}上限 "
                 f"{limit // 1024 // 1024} MB")
        return rep
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        rep.fail("不是有效的 zip 文件")
        return rep
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        rep.fail(f"文件数 {len(infos)} 超过上限 {MAX_FILES}")
        return rep
    declared = sum(i.file_size for i in infos)
    if declared > max(len(data), 1) * MAX_RATIO or declared > MAX_TOTAL:
        rep.fail(f"解压后 {declared // 1024} KB,超过压缩量的 {MAX_RATIO} 倍或 "
                 f"{MAX_TOTAL // 1024 // 1024} MB 上限(疑似 zip 炸弹)")
        return rep
    seen: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        why = _bad_path(name)
        if why:
            rep.fail(f"{name}:{why}")
            continue
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            rep.fail(f"{name}:不能是符号链接")
            continue
        if name in seen:
            rep.fail(f"{name}:路径重复")
            continue
        seen.add(name)
        ctype = content_type(name)
        if ctype is None:
            rep.fail(f"{name}:不支持的文件类型")
            continue
        if info.file_size > MAX_FILE:
            rep.fail(f"{name}:单文件 {info.file_size // 1024} KB 超过 5 MB")
            continue
        with zf.open(info) as fh:
            blob = fh.read(MAX_FILE + 1)
        if len(blob) > MAX_FILE:
            rep.fail(f"{name}:实际大小超过 5 MB(zip 目录声明的大小不对)")
            continue
        total += len(blob)
        if total > MAX_TOTAL:
            rep.fail("解压总量超过上限(zip 目录声明的大小不对)")
            break
        rep.blobs[name] = blob
        rep.files[name] = {"size": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
                           "type": ctype}
    if not rep.ok:
        return rep
    if "index.html" not in rep.files:
        rep.fail("根目录缺 index.html")
    if "superz.json" not in rep.files:
        rep.fail("根目录缺 superz.json")
        return rep
    try:
        manifest = json.loads(rep.blobs["superz.json"].decode("utf-8"))
        assert isinstance(manifest, dict)
    except Exception:
        rep.fail("superz.json 不是合法的 JSON 对象")
        return rep
    rep.manifest = manifest
    if str(manifest.get("sdk")) != "2":
        rep.fail('superz.json 的 sdk 必须是 "2"')
    if manifest.get("kind", kind) != kind:
        rep.fail(f"superz.json 的 kind 是 {manifest.get('kind')},和应用类型 {kind} 不一致")
    if manifest.get("orientation", "portrait") not in ORIENTATIONS:
        rep.fail("superz.json 的 orientation 只能是 portrait / landscape / any")
    color = manifest.get("background_color", "#F0EEE6")
    if not isinstance(color, str) or not _COLOR.match(color):
        rep.fail("superz.json 的 background_color 要写成 #RRGGBB")
    if not isinstance(manifest.get("spa_fallback", False), bool):
        rep.fail("superz.json 的 spa_fallback 要是 true 或 false")
    for name, blob in rep.blobs.items():
        if not name.endswith(".html"):
            continue
        text = blob.decode("utf-8", errors="ignore")
        if _EXTERNAL_SCRIPT.search(text):
            rep.warnings.append(f"{name}:引用了外部脚本 —— 托管页的 CSP 只许同源脚本,上线后会被拦下")
        if _EXTERNAL_STYLE.search(text):
            rep.warnings.append(f"{name}:引用了外部样式或资源 —— 会被 CSP 拦下,请打进包里")
    return rep


# ---------------- 托管出口的返回头 ----------------

def build_csp(*, request_domains: list[str], frame_ancestors: list[str], report_uri: str) -> str:
    declared = " ".join(d for d in request_domains if d)
    ancestors = " ".join(frame_ancestors) if frame_ancestors else "'none'"
    parts = [
        "default-src 'self'",
        "script-src 'self' 'wasm-unsafe-eval'",
        "style-src 'self' 'unsafe-inline'",
        f"img-src 'self' data: blob: {declared}".rstrip(),
        "font-src 'self' data:",
        f"media-src 'self' blob: {declared}".rstrip(),
        f"connect-src 'self' {declared}".rstrip(),
        "frame-src 'none'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'none'",
        f"frame-ancestors {ancestors}",
        f"report-uri {report_uri}",
    ]
    return "; ".join(parts)


PERMISSIONS_POLICY = ("camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
                      "bluetooth=(), serial=(), hid=()")
