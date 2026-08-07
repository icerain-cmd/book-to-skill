import json
from pathlib import Path

from book_to_skill import research


def test_init_project_creates_research_layout(tmp_path):
    root = research.init_project("My Research", tmp_path / "workspace")

    assert (root / "research.json").exists()
    assert (root / "SKILL.md").exists()
    assert (root / "sources" / "text").is_dir()
    assert (root / "concepts").is_dir()
    assert (root / "arguments").is_dir()
    assert (root / "citations").is_dir()
    assert (root / "papers").is_dir()

    manifest = json.loads((root / "research.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "My Research"
    assert manifest["slug"] == "my-research"
    assert manifest["sources"] == []


def test_add_sources_extracts_text_and_deduplicates(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    source = tmp_path / "paper.md"
    source.write_text("# Paper\n\nA research claim with evidence.\n", encoding="utf-8")

    added = research.add_sources(root, [str(source)])
    assert len(added) == 1
    assert (root / added[0]["text_file"]).exists()
    assert (root / added[0]["metadata_file"]).exists()

    duplicate = research.add_sources(root, [str(source)])
    assert duplicate == []

    manifest = json.loads((root / "research.json").read_text(encoding="utf-8"))
    assert len(manifest["sources"]) == 1
    assert manifest["sources"][0]["filename"] == "paper.md"


def test_status_aggregates_source_counts(tmp_path):
    root = research.init_project("Status Test", tmp_path / "workspace")
    source = tmp_path / "note.txt"
    source.write_text("one two three four", encoding="utf-8")
    research.add_sources(root, [str(source)])

    status = research.project_status(root)
    assert status["source_count"] == 1
    assert status["total_words"] == 4
    assert status["estimated_tokens"] > 0
