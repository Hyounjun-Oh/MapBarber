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
