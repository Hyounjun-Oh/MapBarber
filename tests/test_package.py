import os
import xml.etree.ElementTree as ElementTree

import mapbarber

PACKAGE = os.path.dirname(mapbarber.__file__)
DOCS = os.path.join(os.path.dirname(PACKAGE), "docs", "media")


def test_icon_and_logos_are_valid_svg():
    for path in (os.path.join(PACKAGE, "assets", "icon.svg"), os.path.join(DOCS, "logo-light.svg"),
                 os.path.join(DOCS, "logo-dark.svg")):
        root = ElementTree.parse(path).getroot()
        assert root.tag.endswith("svg") and root.get("viewBox")


def test_readmes_are_complete_in_every_language():
    import re
    root = os.path.dirname(PACKAGE)
    names = ["README.md"] + [os.path.join("docs", "i18n", f"README.{code}.md") for code in ("ko", "ja", "zh", "de", "es")]
    sections = None
    for name in names:
        here = os.path.dirname(os.path.join(root, name))
        with open(os.path.join(root, name), encoding="utf-8") as f:
            text = f.read()
        for other in names:
            link = os.path.relpath(os.path.join(root, other), here).replace(os.sep, "/")
            assert other == name or f'href="{link}"' in text, (name, link)
        count = len(re.findall(r"^## ", text, flags=re.MULTILINE))
        sections = sections or count
        assert count == sections, (name, count, sections)
        for target in re.findall(r"\]\(([^)#:]+)\)|srcset=\"([^\"]+)\"|src=\"([^\"]+)\"", text):
            target = next(part for part in target if part)
            if not target.startswith("http"):
                assert os.path.exists(os.path.join(here, target)), (name, target)
