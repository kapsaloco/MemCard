from pathlib import Path

from memcard import __version__
from memcard.about import AUTHOR, REPOSITORY, about_html, about_text


def test_about_text_matches_shared_metadata_and_distribution_file():
    text = about_text()
    assert __version__ in text
    assert AUTHOR.strip()
    assert AUTHOR in text
    assert REPOSITORY.startswith("https://github.com/")
    assert REPOSITORY in text
    assert f"{REPOSITORY}/issues" in text
    assert (Path(__file__).resolve().parents[1] / "ABOUT.txt").read_text(encoding="utf-8") == text


def test_about_html_contains_clickable_repository_and_issues():
    html = about_html()
    assert f'href="{REPOSITORY}"' in html
    assert f'href="{REPOSITORY}/issues"' in html
    assert __version__ in html
    assert AUTHOR in html
