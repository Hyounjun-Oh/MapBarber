import os
import re
import string

from mapbarber import i18n

PACKAGE = os.path.dirname(i18n.__file__)
DYNAMIC = {"tool_": ("view", "select", "delete", "add", "pen", "line", "rectangle", "fill"),
           "view_": ("top", "front", "side", "iso", "fit"), "kind_": ("voxel", "cloud", "grid"),
           "controls_": ("general", "voxel", "cloud", "grid")}


def placeholders(text):
    return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name)


def used_keys():
    pattern = re.compile(r"""\b(?:t|tr|tr_)\(\s*["']([a-z_]+)["']""")
    keys = set()
    for name in os.listdir(PACKAGE):
        if name.endswith(".py"):
            with open(os.path.join(PACKAGE, name), encoding="utf-8") as f:
                source = f.read()
            keys |= set(pattern.findall(source))
            keys |= set(re.findall(r'"(state_[a-z]+|delete_selection|select_all|invert_selection|clear_selection)"', source))
    keys = {k for k in keys if not k.endswith("_")}
    for prefix, names in DYNAMIC.items():
        keys |= {prefix + n for n in names}
    return keys


def test_every_language_is_complete():
    reference = i18n.table("en")
    for code in i18n.LANGUAGES:
        current = i18n.table(code)
        assert set(current) == set(reference), (code, set(reference) ^ set(current))
        for key, text in current.items():
            assert placeholders(text) == placeholders(reference[key]), (code, key)


def test_code_uses_only_defined_keys():
    missing = used_keys() - set(i18n.table("en"))
    assert not missing, missing


def test_unknown_language_falls_back():
    assert i18n.Translator("xx").language in i18n.LANGUAGES
    assert i18n.Translator("ko")("save") == "저장"
