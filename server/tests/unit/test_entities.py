"""消息实体:UTF-16 偏移(DEV-PROMPTS-40 §5.2)。「👍」在 Python 里长 1、在 UTF-16 里长 2。"""
import pytest

from app.services.entities import (EntityError, auto_entities, mentioned_usernames,
                                   slice_utf16, utf16_len, validate_entities)


def test_utf16_len():
    assert utf16_len("abc") == 3
    assert utf16_len("👍") == 2
    assert utf16_len("中文") == 2
    assert utf16_len("𠀀") == 2, "扩展 B 区汉字是代理对"


def test_validate_bounds_and_types():
    text = "👍加粗"
    ok = validate_entities(text, [{"type": "bold", "offset": 2, "length": 2}])
    assert slice_utf16(text, 2, 2) == "加粗" and ok[0]["type"] == "bold"
    with pytest.raises(EntityError):
        validate_entities(text, [{"type": "bold", "offset": 2, "length": 3}])
    with pytest.raises(EntityError):
        validate_entities(text, [{"type": "evil", "offset": 0, "length": 1}])
    with pytest.raises(EntityError):
        validate_entities("x", [{"type": "text_link", "offset": 0, "length": 1,
                                 "url": "javascript:alert(1)"}])


def test_auto_entities_offsets_after_emoji():
    text = "👍 看 https://chaojizan.cc/a, 找 @alice_1 #外卖"
    found = {e["type"]: e for e in auto_entities(text)}
    assert slice_utf16(text, found["url"]["offset"], found["url"]["length"]) == \
        "https://chaojizan.cc/a", "结尾的英文逗号不算链接"
    assert slice_utf16(text, found["mention"]["offset"], found["mention"]["length"]) == "@alice_1"
    assert slice_utf16(text, found["hashtag"]["offset"], found["hashtag"]["length"]) == "#外卖"
    assert mentioned_usernames(text, list(found.values())) == {"alice_1"}


def test_code_blocks_are_not_scanned():
    text = "`@bob123` 和 @carol9"
    code = [{"type": "code", "offset": 0, "length": 8}]
    found = auto_entities(text, code)
    assert [slice_utf16(text, e["offset"], e["length"]) for e in found] == ["@carol9"]
