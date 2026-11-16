"""Shared About content for the application and Windows distribution."""

from html import escape

from . import __version__


AUTHOR = "George Kapsalakos"
REPOSITORY = "https://github.com/kapsaloco/MemCard"
DESCRIPTION = "Game-save backup and recovery for PCSX2 and RPCS3."
DISCLAIMER = "Independent project. Not affiliated with PCSX2, RPCS3, or Sony."


def about_text() -> str:
    return (
        f"MemCard\nVersion {__version__} - Alpha\n\n{DESCRIPTION}\n\n"
        f"Created by {AUTHOR}\n\nRepository: {REPOSITORY}\n"
        f"Report an issue: {REPOSITORY}/issues\n\n{DISCLAIMER}\n"
    )


def about_html() -> str:
    return (
        f"<h2>MemCard</h2><p>Version {escape(__version__)} — Alpha</p>"
        f"<p>{escape(DESCRIPTION)}</p><p>Created by <b>{escape(AUTHOR)}</b></p>"
        f'<p><a href="{REPOSITORY}">GitHub repository</a> · '
        f'<a href="{REPOSITORY}/issues">Report an issue</a></p>'
        f"<p>{escape(DISCLAIMER)}</p>"
    )
