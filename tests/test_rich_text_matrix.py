import json
from pathlib import Path
from html.parser import HTMLParser
import pytest
from rich_text import render_inline, plain_text

CASES = json.loads((Path(__file__).resolve().parents[2] / "frontend/src/lib/richTextCases.json").read_text(encoding="utf-8"))


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.hrefs, self.tags, self.text = [], [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "a":
            self.hrefs.append(dict(attrs)["href"])

    def handle_data(self, data):
        self.text.append(data)


@pytest.mark.parametrize("case", CASES, ids=lambda item: item["text"])
def test_server_matches_browser_formatting(case):
    document = Document(render_inline(case["text"]))
    assert "".join(document.text) == case["plain"]
    assert plain_text(case["text"]) == case["plain"]
    assert document.hrefs == case["hrefs"]
    assert set(case["tags"]).issubset(document.tags)
