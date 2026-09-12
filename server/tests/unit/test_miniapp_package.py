"""托管包校验:§5.6 的每条规则一个用例(#322)。恶意包全部要被拒,且报告读得懂。"""
import io
import json
import os
import stat
import zipfile

from app.services.miniapp_package import build_csp, validate_package

MANIFEST = {"sdk": "2", "kind": "app", "orientation": "portrait",
            "background_color": "#F0EEE6", "spa_fallback": False}


def make_zip(files: dict[str, bytes], *, symlink: str | None = None,
             compression=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


def ok_files(**extra) -> dict[str, bytes]:
    files = {"index.html": b"<!doctype html><title>x</title><script src=app.js></script>",
             "app.js": b"console.log(1)", "superz.json": json.dumps(MANIFEST).encode()}
    files.update(extra)
    return files


def test_valid_package_passes_with_manifest_and_hashes():
    rep = validate_package(make_zip(ok_files()), kind="app")
    assert rep.ok, rep.errors
    assert set(rep.files) == {"index.html", "app.js", "superz.json"}
    assert rep.files["index.html"]["type"].startswith("text/html")
    assert len(rep.sha256) == 64 and rep.manifest["sdk"] == "2"


def test_not_a_zip():
    rep = validate_package(b"hello", kind="app")
    assert not rep.ok and "zip" in rep.errors[0]


def test_zip_too_big_for_app_but_fine_for_game():
    # 随机字节不可压缩:三个 4MB 的图,压缩后 12MB —— 超过应用的 10MB、没超小游戏的 30MB
    game_manifest = json.dumps(dict(MANIFEST, kind="game")).encode()
    files = ok_files(**{"superz.json": game_manifest})
    for i in range(3):
        files[f"big{i}.png"] = os.urandom(4 * 1024 * 1024)
    data = make_zip(files)
    rep_app = validate_package(data, kind="app")
    assert not rep_app.ok and any("上限" in e for e in rep_app.errors)
    rep_game = validate_package(data, kind="game")
    assert rep_game.ok, rep_game.errors


def test_zip_bomb_rejected_by_ratio():
    rep = validate_package(make_zip(ok_files(**{"zeros.txt": b"\0" * (8 * 1024 * 1024)})),
                           kind="app")
    assert not rep.ok and any("zip 炸弹" in e for e in rep.errors)


def test_single_file_over_5mb():
    rep = validate_package(make_zip(ok_files(**{"huge.png": os.urandom(5 * 1024 * 1024 + 10)})),
                           kind="app")
    assert not rep.ok and any("5 MB" in e for e in rep.errors)


def test_zip_slip_absolute_backslash_hidden():
    for bad in ("../evil.js", "a/../../evil.js", "/etc/evil.js", "a\\b.js", ".env.js", "a//b.js"):
        rep = validate_package(make_zip(ok_files(**{bad: b"x"})), kind="app")
        assert not rep.ok, bad


def test_symlink_rejected():
    rep = validate_package(make_zip(ok_files(), symlink="link.js"), kind="app")
    assert not rep.ok and any("符号链接" in e for e in rep.errors)


def test_extension_whitelist():
    rep = validate_package(make_zip(ok_files(**{"run.exe": b"MZ"})), kind="app")
    assert not rep.ok and any("不支持的文件类型" in e for e in rep.errors)
    rep = validate_package(make_zip(ok_files(**{"a.php": b"<?php"})), kind="app")
    assert not rep.ok


def test_too_many_files():
    files = ok_files()
    for i in range(1001):
        files[f"f{i}.txt"] = b"x"
    rep = validate_package(make_zip(files), kind="app")
    assert not rep.ok and any("文件数" in e for e in rep.errors)


def test_missing_index_or_manifest():
    files = ok_files()
    del files["index.html"]
    assert any("index.html" in e for e in validate_package(make_zip(files), kind="app").errors)
    files = ok_files()
    del files["superz.json"]
    assert any("superz.json" in e for e in validate_package(make_zip(files), kind="app").errors)


def test_manifest_rules():
    for bad in ({"sdk": "1"}, {"orientation": "sideways"}, {"background_color": "red"},
                {"spa_fallback": "yes"}, {"kind": "game"}):
        m = dict(MANIFEST, **bad)
        rep = validate_package(make_zip(ok_files(**{"superz.json": json.dumps(m).encode()})),
                               kind="app")
        assert not rep.ok, bad
    rep = validate_package(make_zip(ok_files(**{"superz.json": b"[1,2]"})), kind="app")
    assert not rep.ok


def test_external_script_is_a_warning_not_an_error():
    html = b'<script src="https://cdn.example.com/x.js"></script><link href="//cdn/x.css">'
    rep = validate_package(make_zip(ok_files(**{"index.html": html})), kind="app")
    assert rep.ok
    assert len(rep.warnings) == 2


def test_csp_only_allows_self_and_declared_domains():
    csp = build_csp(request_domains=["https://api.example.com"],
                    frame_ancestors=["https://chaojizan.cc"], report_uri="/mini-apps/csp-report")
    assert "script-src 'self' 'wasm-unsafe-eval'" in csp
    assert "connect-src 'self' https://api.example.com" in csp
    assert "frame-ancestors https://chaojizan.cc" in csp
    assert "frame-src 'none'" in csp and "object-src 'none'" in csp
    assert "https://api.example.com" not in csp.split("script-src")[1].split(";")[0]
    none = build_csp(request_domains=[], frame_ancestors=[], report_uri="/r")
    assert "frame-ancestors 'none'" in none and "connect-src 'self';" in none
