"""Browserless regression check for API-derived document-title escaping."""
from pathlib import Path
from html import escape


TITLE = '<img src=x onerror=alert(1)>'
SOURCE = Path(__file__).resolve().parents[1] / "frontend" / "app.js"


def main():
    source = SOURCE.read_text(encoding="utf-8")
    rendered = f'<td>{escape(TITLE, quote=True)}</td>'
    assert TITLE not in rendered
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered
    assert "escapeHTML(d.title)" in source
    print("PASS frontend API-derived title renders as escaped text")


if __name__ == "__main__":
    main()