import os
import xml.etree.ElementTree as ElementTree

import mapbarber

PACKAGE = os.path.dirname(mapbarber.__file__)
DOCS = os.path.join(os.path.dirname(PACKAGE), "docs")


def test_icon_and_logos_are_valid_svg():
    for path in (os.path.join(PACKAGE, "assets", "icon.svg"), os.path.join(DOCS, "logo-light.svg"),
                 os.path.join(DOCS, "logo-dark.svg")):
        root = ElementTree.parse(path).getroot()
        assert root.tag.endswith("svg") and root.get("viewBox")


def test_readmes_are_complete_in_every_language():
    import re
    root = os.path.dirname(PACKAGE)
    names = ["README.md"] + [f"README.{code}.md" for code in ("ko", "ja", "zh", "de", "es")]
    sections = None
    for name in names:
        with open(os.path.join(root, name), encoding="utf-8") as f:
            text = f.read()
        for other in names:
            assert other == name or f'href="{other}"' in text, (name, other)
        count = len(re.findall(r"^## ", text, flags=re.MULTILINE))
        sections = sections or count
        assert count == sections, (name, count, sections)
        for image in re.findall(r"\]\((docs/[^)]+)\)|srcset=\"(docs/[^\"]+)\"|src=\"(docs/[^\"]+)\"", text):
            target = next(part for part in image if part)
            assert os.path.exists(os.path.join(root, target)), (name, target)
