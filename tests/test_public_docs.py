"""The README is the public teaching surface; keep its adopted presentation."""
import re
from pathlib import Path
from html.parser import HTMLParser

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]


def test_reservation_narrative_and_boundary():
    readme = (ROOT / "README.md").read_text()
    assert readme.splitlines()[0] == "# AAC: two tenants, one reservation made"
    assert "unpaid" not in readme and "synthetic" not in readme
    normalized = " ".join(readme.split())
    assert normalized.count("supplier integration and payment are omitted for clarity") == 1
    assert "not a guaranteed price hold" in normalized
    assert "https://cascadeauth.github.io/aac-starter-guide/" in readme


def test_every_named_requirement_is_linked_and_explains_where_it_runs():
    readme = (ROOT / "README.md").read_text()
    section = readme.split("## Requirements\n", 1)[1].split("## 1.", 1)[0]
    assert "Version used here" not in section
    rows = [line.split("|")[1:3] for line in section.splitlines() if line.startswith("| ")][1:]
    assert len(rows) == 6
    for component, supplied in rows:
        links = re.findall(r"\[[^\]]+\]\(https://[^)]+\)", component)
        assert links
        assert re.sub(r"\[[^\]]+\]\(https://[^)]+\)", "", component).strip(" / ") == ""
        assert supplied.strip()
    assert len(re.findall(r"\]\(https://", rows[-1][0])) == 2
    assert "host Python" in section and "inside the application image" in section
    assert "released-components.json" in section


def test_rendered_requirements_link_every_component():
    class Table(HTMLParser):
        def __init__(self):
            super().__init__()
            self.cells, self.cell, self.link, self.text, self.unlinked = [], False, False, "", ""

        def handle_starttag(self, tag, attrs):
            if tag == "td":
                self.cell, self.text, self.unlinked = True, "", ""
            if tag == "a":
                self.link = True

        def handle_endtag(self, tag):
            if tag == "a":
                self.link = False
            if tag == "td":
                self.cells.append((self.text, self.unlinked)); self.cell = False

        def handle_data(self, value):
            if self.cell:
                self.text += value
                if not self.link:
                    self.unlinked += value

    readme = (ROOT / "README.md").read_text()
    requirements = readme.split("## Requirements\n", 1)[1].split("## 1.", 1)[0]
    rendered = MarkdownIt("commonmark").enable("table").render(requirements)
    table = Table(); table.feed(rendered)
    assert len(table.cells) == 12
    for text, unlinked in table.cells[::2]:
        assert text.strip() and not unlinked.strip(" / ")
    assert "Version used here" not in rendered
