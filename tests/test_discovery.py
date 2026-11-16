from pathlib import Path

import pytest

import main
from memcard import discovery
from memcard.paths import BackupError


def test_finds_cards_in_redirected_documents(tmp_path, monkeypatch):
    documents = tmp_path / "redirected" / "My Documents"
    cards = documents / "PCSX2" / "memcards"
    cards.mkdir(parents=True)
    monkeypatch.setattr(discovery, "documents_directory", lambda: documents)
    assert discovery.find_pcsx2_memcards() == cards


@pytest.mark.parametrize("kind", ["absent", "file", "unavailable"])
def test_discovery_failure_falls_back(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(discovery, "documents_directory", lambda: tmp_path)
    if kind == "file":
        (tmp_path / "PCSX2").mkdir()
        (tmp_path / "PCSX2" / "memcards").write_text("not a folder")
    elif kind == "unavailable":
        def fail():
            raise OSError("Documents unavailable")
        monkeypatch.setattr(discovery, "documents_directory", fail)
    assert discovery.find_pcsx2_memcards() is None


def test_explicit_source_wins(monkeypatch):
    def unexpected():
        pytest.fail("Should not discover when --source was supplied")
    monkeypatch.setattr(main, "find_pcsx2_memcards", unexpected)
    assert main.select_source(Path("custom")) == Path("custom")


def test_detected_source_needs_no_path_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "find_pcsx2_memcards", lambda: tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Unexpected path prompt"))
    assert main.select_source(None) == tmp_path


def test_missing_source_prompts_for_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "find_pcsx2_memcards", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _: f'"{tmp_path}"')
    assert main.select_source(None) == tmp_path


def test_missing_source_noninteractive_reports_action(monkeypatch):
    monkeypatch.setattr(main, "find_pcsx2_memcards", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Unexpected prompt with --yes"))
    with pytest.raises(BackupError, match="Provide --source"):
        main.select_source(None, noninteractive=True)


def test_empty_selection_cancels(monkeypatch):
    monkeypatch.setattr(main, "find_pcsx2_memcards", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _: "")
    with pytest.raises(BackupError, match="No memory-card directory"):
        main.select_source(None)


def test_detected_backup_still_prompts_before_writing(tmp_path, monkeypatch):
    from functools import partial
    from uuid import uuid4
    from memcard.instance import single_instance
    monkeypatch.setattr(main, "single_instance", partial(single_instance, name=f"Local\\MemCard.Test.{uuid4()}"))
    source, library = tmp_path / "memcards", tmp_path / "library"
    source.mkdir()
    library.mkdir()
    (source / "card.ps2").write_bytes(b"test")
    monkeypatch.setattr(main, "find_pcsx2_memcards", lambda: source)
    monkeypatch.setattr("sys.argv", ["main.py", "backup-pcsx2", "--library", str(library), "--emulator-closed"])
    prompts = []
    def decline(prompt):
        prompts.append(prompt)
        return "n"
    monkeypatch.setattr("builtins.input", decline)
    assert main.main() == 0
    assert prompts == ["Create this backup? [y/N] "]
    assert not list(library.iterdir())
