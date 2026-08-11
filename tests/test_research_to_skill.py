import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
import uuid

import pytest

from book_to_skill import research
from book_to_skill.exceptions import ExtractionError


def source_file(tmp_path, name="paper.md", content="# Paper\n\nA claim with evidence.\n"):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def manifest(root):
    return json.loads((root / "research.json").read_text(encoding="utf-8"))


def test_init_creates_canonical_layout_and_skill(tmp_path):
    root = research.init_project("나의 연구", tmp_path / "workspace")
    data = manifest(root)
    assert data["schema_version"] == 1
    assert data["project"]["name"] == "나의 연구"
    assert data["project"]["slug"] == "research"
    uuid.UUID(data["project"]["id"])
    for relative in research.PROJECT_DIRS:
        assert (root / relative).is_dir()
    assert (root / "relations/knowledge-graph.json").is_file()
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    assert "## Retrieval order" in skill
    assert "author" in skill and "external" in skill


def test_init_rejects_empty_name_and_existing_workspace(tmp_path):
    with pytest.raises(research.ResearchError):
        research.init_project(" ", tmp_path / "empty")
    root = research.init_project("Test", tmp_path / "existing")
    with pytest.raises(FileExistsError):
        research.init_project("Test", root)
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "SKILL.md").write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match="non-empty"):
        research.init_project("Test", occupied)
    assert (occupied / "SKILL.md").read_text(encoding="utf-8") == "keep"


def test_add_unicode_source_extracts_and_deduplicates(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    source = source_file(tmp_path, "생태 연구.md")
    added = research.add_sources(root, [str(source)])
    assert len(added) == 1
    record = added[0]
    assert record["filename"] == "생태 연구.md"
    assert len(record["sha256"]) == 64
    assert record["authors"] == [] and record["doi"] is None
    assert research.add_sources(root, [str(source)]) == []
    assert manifest(root)["sources"] == [record]


def test_source_id_is_stable_across_projects(tmp_path):
    source = source_file(tmp_path)
    roots = [research.init_project(str(i), tmp_path / f"w{i}") for i in range(2)]
    ids = [research.add_sources(root, [str(source)])[0]["id"] for root in roots]
    assert ids[0] == ids[1]


def test_multiple_mixed_sources_and_status(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    first = source_file(tmp_path, "a.md", "one two")
    second = source_file(tmp_path, "b.txt", "three four five")
    added = research.add_sources(root, [str(first), str(second)])
    status = research.project_status(root)
    assert len(added) == status["source_count"] == 2
    assert status["total_words"] == 5
    assert status["dirty_source_count"] == 2


def test_failed_extraction_is_partial_and_reported(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    good = source_file(tmp_path, "good.md")
    bad = source_file(tmp_path, "bad.md", "different content")

    def extract(path, *_args):
        if path.name == "bad.md":
            raise ExtractionError("broken")
        return {"text": "valid text", "format": "markdown", "words": 2,
                "estimated_tokens": 2, "extraction_method": "text"}

    with mock.patch("book_to_skill.research.extract_single_file", side_effect=extract):
        added, failures = research.SourceRegistry(research.ResearchProject(root)).add(
            [str(good), str(bad)]
        )
    assert len(added) == len(failures) == 1
    assert failures[0]["path"].endswith("bad.md")
    assert len(manifest(root)["sources"]) == 1


def test_empty_extraction_is_failure(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    source = source_file(tmp_path)
    with mock.patch("book_to_skill.research.extract_single_file", return_value={"text": ""}):
        added, failures = research.SourceRegistry(research.ResearchProject(root)).add([str(source)])
    assert added == [] and len(failures) == 1


def test_corrupt_and_wrong_schema_manifest_are_clear_errors(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    (root / "research.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(research.ManifestError, match="Cannot read"):
        research.project_status(root)
    (root / "research.json").write_text('{"schema_version": 99}', encoding="utf-8")
    with pytest.raises(research.ManifestError, match="Invalid research.json"):
        research.project_status(root)


def add_claim_dependency(root, source_id):
    data = manifest(root)
    claim = {
        "id": "claim-001", "text": "A claim", "origin": "author",
        "source_ids": [source_id], "evidence": [{"source_id": source_id,
        "locator": {"page": None, "section": None, "paragraph": None},
        "quote": None, "summary": "Explicit in source", "evidence_type": "explicit"}],
        "concept_ids": [], "confidence": 0.9, "first_seen": None, "last_seen": None,
    }
    data["claims"].append(claim)
    (root / "claims/claim-001.json").write_text(json.dumps(claim), encoding="utf-8")
    (root / "research.json").write_text(json.dumps(data), encoding="utf-8")


def test_remove_protects_dependencies_and_cascade_removes_them(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    record = research.add_sources(root, [str(source_file(tmp_path))])[0]
    add_claim_dependency(root, record["id"])
    with pytest.raises(research.ResearchError, match="Removal blocked"):
        research.remove_source(root, record["id"])
    research.remove_source(root, record["id"], cascade=True)
    assert manifest(root)["sources"] == []
    assert manifest(root)["claims"] == []
    assert not (root / record["text_file"]).exists()


def test_inspect_list_and_compile_plan(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    record = research.add_sources(root, [str(source_file(tmp_path))])[0]
    assert research.list_sources(root)[0]["id"] == record["id"]
    assert research.inspect_item(root, "source", record["id"])["sha256"] == record["sha256"]
    plan = research.compile_project(root)
    assert plan["dirty_sources"][0]["id"] == record["id"]
    assert plan["status"] == "semantic-compilation-required"
    completed = research.complete_compilation(root, [record["id"]])
    assert completed["completed_sources"] == [record["id"]]
    assert research.project_status(root)["dirty_source_count"] == 0
    assert research.compile_project(root)["status"] == "up-to-date"


def test_claim_and_concept_schema_validation():
    assert research.ClaimRegistry.validate({"id": "c", "text": "x", "origin": "invented"})
    assert not research.ClaimRegistry.validate(
        {"id": "c", "text": "x", "origin": "uncertain", "evidence": []}
    )
    assert research.ConceptRegistry.validate({"id": "x", "versions": [{}]})


def test_validate_detects_claim_and_dangling_graph_errors(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    data = manifest(root)
    data["claims"].append({"id": "claim-1", "text": "x", "origin": "bad",
                           "source_ids": ["missing"], "concept_ids": ["missing"],
                           "evidence": []})
    (root / "research.json").write_text(json.dumps(data), encoding="utf-8")
    (root / "relations/knowledge-graph.json").write_text(json.dumps({
        "nodes": [{"id": "claim-1", "type": "claim"}],
        "edges": [{"source": "claim-1", "target": "missing", "type": "supports"}],
    }), encoding="utf-8")
    findings = research.validate_project(root)
    codes = {item["code"] for item in findings if item["level"] == "ERROR"}
    assert {"invalid-claim", "broken-source-ref", "missing-concept-ref", "invalid-graph"} <= codes


def test_validate_detects_path_traversal(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    data = manifest(root)
    data["sources"].append({"id": "bad", "text_file": "../../outside", "metadata_file": "x"})
    (root / "research.json").write_text(json.dumps(data), encoding="utf-8")
    assert any(f["code"] == "unsafe-path" for f in research.validate_project(root))


def test_validate_detects_evidence_source_and_cross_type_duplicate(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    data = manifest(root)
    data["concepts"].append({"id": "same", "versions": []})
    data["claims"].append({
        "id": "same", "text": "x", "origin": "author", "source_ids": [],
        "concept_ids": [], "evidence": [{"source_id": "missing", "evidence_type": "explicit"}],
    })
    (root / "research.json").write_text(json.dumps(data), encoding="utf-8")
    findings = research.validate_project(root)
    messages = "\n".join(item["message"] for item in findings)
    assert "reused across artifact types" in messages
    assert "evidence -> missing" in messages


@pytest.mark.parametrize("export_format,suffix", [("json", ".json"), ("markdown", ".md"), ("skill", ".zip")])
def test_exports(tmp_path, export_format, suffix):
    root = research.init_project("Corpus", tmp_path / "workspace")
    research.add_sources(root, [str(source_file(tmp_path))])
    target = research.export_project(root, export_format, tmp_path / "exports")
    assert target.is_file() and target.suffix == suffix


def test_skill_export_inside_project_does_not_archive_itself(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    target = research.export_project(root, "skill", root)
    assert target.is_file()
    import zipfile
    with zipfile.ZipFile(target) as archive:
        assert target.name not in archive.namelist()


def test_cli_help_and_workflow(tmp_path, capsys):
    assert research.main(["init", "Test Research", "--dir", str(tmp_path / "project")]) == 0
    source = source_file(tmp_path)
    assert research.main(["add", str(source), "--project", str(tmp_path / "project")]) == 0
    for command in ("status", "list", "compile", "validate"):
        assert research.main([command, "--project", str(tmp_path / "project")]) == 0
    assert "PASS" in capsys.readouterr().out


def test_python39_compatible_annotations():
    source = Path(research.__file__).read_text(encoding="utf-8")
    assert " | None" not in source


def test_lock_acquire_double_acquire_release_and_unicode_identity(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    lock = research.ProjectLock(root)
    with mock.patch.object(
        research, "_local_identity", return_value={"agent": "콜코", "machine": "연구-PC"}
    ):
        value = lock.acquire("코덱스", "semantic-write")
        assert value["owner"] == "코덱스" and value["host"] == "연구-PC"
        with pytest.raises(research.ResearchLockError, match="코덱스"):
            lock.acquire("다른-agent", "compile")
        lock.release("코덱스")
    assert lock.status()["state"] == "unlocked"


def test_stale_lock_requires_forced_break(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    lock = research.ProjectLock(root)
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    (root / research.LOCK_NAME).write_text(json.dumps({
        "schema_version": 1, "owner": "old", "host": "PC1", "pid": 1,
        "operation": "compile", "created_at": expired.isoformat(),
        "expires_at": expired.isoformat(),
    }), encoding="utf-8")
    assert lock.status()["state"] == "stale"
    with pytest.raises(research.ResearchLockError, match="--force"):
        lock.break_lock()
    lock.break_lock(force=True)
    assert lock.status()["state"] == "unlocked"


def test_automatic_write_lock_blocks_and_cleans_up_after_exception(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    lock = research.ProjectLock(root)
    lock.acquire("other", "semantic-write")
    with pytest.raises(research.ResearchLockError):
        research.compile_project(root)
    lock.break_lock(force=True)
    with mock.patch("book_to_skill.research._atomic_json", side_effect=OSError("boom")):
        with pytest.raises(OSError, match="boom"):
            research.compile_project(root)
    assert lock.status()["state"] == "unlocked"


def test_project_uuid_migration_is_persistent_and_preserves_ids(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    data = manifest(root)
    del data["project"]["id"]
    data["sources"] = [{"id": "source-stable"}]
    (root / "research.json").write_text(json.dumps(data), encoding="utf-8")
    first = research.ResearchProject(root).manifest
    second = research.ResearchProject(root).manifest
    uuid.UUID(first["project"]["id"])
    assert first["project"]["id"] == second["project"]["id"]
    assert second["sources"][0]["id"] == "source-stable"


def test_preflight_ready_and_locked(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    ready = research.project_preflight(root)
    assert ready["result"] == "READY" and ready["validation"] == "PASS"
    lock = research.ProjectLock(root)
    lock.acquire("codex", "semantic-write")
    assert research.project_preflight(root)["result"] == "LOCKED"
    lock.break_lock(force=True)


def test_handoff_generation_and_lock_cleanup(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    target = research.generate_handoff(root)
    text = target.read_text(encoding="utf-8")
    assert "자동 생성" in text and manifest(root)["project"]["id"] in text
    assert research.ProjectLock(root).status()["state"] == "unlocked"


def test_windows_style_path_and_atomic_replace_are_portable(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    data = manifest(root)
    data["sources"].append({
        "id": "windows-path", "source_path": r"R:\\research-to-skill\\sources\\paper.pdf",
        "text_file": "sources/text/windows-path.txt",
        "metadata_file": "sources/meta/windows-path.json",
    })
    research._atomic_json(root / "research.json", data)
    research._atomic_text(root / "atomic.txt", "first")
    research._atomic_text(root / "atomic.txt", "second")
    assert (root / "atomic.txt").read_text(encoding="utf-8") == "second"
    assert research.ResearchProject(root).manifest["sources"][0]["source_path"].startswith("R:")


def semantic_workspace(tmp_path):
    root = research.init_project("Corpus", tmp_path / "workspace")
    data = manifest(root)
    data["concepts"] = [{"id": "alpha", "name": "Alpha", "versions": []}]
    data["claims"] = [{
        "id": "claim-001", "text": "Canonical claim", "origin": "author",
        "source_ids": [], "concept_ids": ["alpha"], "evidence": [],
    }]
    research._atomic_json(root / "research.json", data)
    research._atomic_text(
        root / "concepts/alpha.md",
        "# Alpha\n\n## Supporting claims\n\n_None._\n\n## Sources\n\n_None._\n",
    )
    research._atomic_json(root / "claims/claim-001.json", data["claims"][0])
    return root


def test_sync_artifacts_matches_manifest_and_is_idempotent(tmp_path):
    root = semantic_workspace(tmp_path)
    first = research.synchronize_derived_artifacts(root)
    assert first == {
        "concept_artifacts_changed": 1,
        "claim_artifacts_changed": 0,
        "topic_index_changed": 1,
    }
    assert research.synchronize_derived_artifacts(root) == {
        "concept_artifacts_changed": 0,
        "claim_artifacts_changed": 0,
        "topic_index_changed": 0,
    }
    assert research._markdown_section(
        (root / "concepts/alpha.md").read_text(encoding="utf-8"), "Supporting claims"
    ) == "- claim-001"
    assert (root / "topic-index.md").read_text(encoding="utf-8") == research._render_topic_index(
        manifest(root)
    )
    assert not [item for item in research.validate_project(root) if item["level"] == "ERROR"]


def test_validate_detects_missing_and_dangling_supporting_claims(tmp_path):
    root = semantic_workspace(tmp_path)
    findings = research.validate_project(root)
    assert any(
        item["code"] == "stale-concept-artifact" and "claim-001" in item["message"]
        for item in findings
    )
    path = root / "concepts/alpha.md"
    research._atomic_text(
        path,
        research._replace_markdown_section(
            path.read_text(encoding="utf-8"), "Supporting claims", "- claim-999"
        ),
    )
    codes = {item["code"] for item in research.validate_project(root)}
    assert "dangling-supporting-claim" in codes
    assert "stale-concept-artifact" in codes


def test_validate_detects_topic_and_claim_artifact_drift(tmp_path):
    root = semantic_workspace(tmp_path)
    research.synchronize_derived_artifacts(root)
    (root / "topic-index.md").write_text(
        "# Topic Index\n\n| Concept | Start here | Supporting claims |\n"
        "|---|---|---|\n| Alpha | `concepts/alpha.md` | `claim-999` |\n",
        encoding="utf-8",
    )
    artifact = json.loads((root / "claims/claim-001.json").read_text(encoding="utf-8"))
    artifact["concept_ids"] = []
    research._atomic_json(root / "claims/claim-001.json", artifact)
    codes = {item["code"] for item in research.validate_project(root)}
    assert {"dangling-topic-claim", "stale-topic-index", "claim-artifact-drift"} <= codes


def test_locator_validation_and_evidence_source_mismatch(tmp_path):
    claim = {
        "id": "claim-locator", "text": "x", "origin": "author",
        "source_ids": ["source-a"], "concept_ids": [],
        "evidence": [{
            "source_id": "source-b", "evidence_type": "explicit",
            "locator": {"page": 0, "section": " ", "paragraph": None},
        }],
    }
    errors = research.ClaimRegistry.validate(claim)
    assert any("positive integer" in error for error in errors)
    assert any("non-empty string" in error for error in errors)
    claim["evidence"][0]["locator"] = {"page": None, "section": None, "paragraph": None}
    assert "evidence locator cannot be empty" in research.ClaimRegistry.validate(claim)

    root = research.init_project("Locator", tmp_path / "locator-workspace")
    data = manifest(root)
    data["sources"] = [
        {"id": source_id, "sha256": source_id, "compiled_hash": source_id,
         "text_file": f"sources/text/{source_id}.txt",
         "metadata_file": f"sources/meta/{source_id}.json"}
        for source_id in ("source-a", "source-b")
    ]
    for source in data["sources"]:
        research._atomic_text(root / source["text_file"], "source")
        research._atomic_json(root / source["metadata_file"], source)
    claim["evidence"][0]["locator"] = {"page": 90, "section": "2.2 Section", "paragraph": None}
    data["claims"] = [claim]
    research._atomic_json(root / "research.json", data)
    research._atomic_json(root / "claims/claim-locator.json", claim)
    research._atomic_text(root / "topic-index.md", research._render_topic_index(data))
    assert any(
        item["code"] == "evidence-source-mismatch" for item in research.validate_project(root)
    )


def test_corrected_locator_regression():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/research-locator-corrections.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(fixture) == {"claim-014", "claim-017"}
    for claim_id, locator in fixture.items():
        claim = {
            "id": claim_id, "text": "unchanged", "origin": "author",
            "source_ids": ["artificial-nature"], "concept_ids": [],
            "evidence": [{
                "source_id": "artificial-nature", "evidence_type": "explicit",
                "locator": locator,
            }],
        }
        assert not research.ClaimRegistry.validate(claim)


def test_sync_rejects_unsafe_artifact_ids(tmp_path):
    root = semantic_workspace(tmp_path)
    data = manifest(root)
    data["concepts"][0]["id"] = "../../outside"
    research._atomic_json(root / "research.json", data)
    with pytest.raises(research.ResearchError, match="Unsafe concept ID"):
        research.synchronize_derived_artifacts(root)
    assert research.ProjectLock(root).status()["state"] == "unlocked"


def test_complete_consumes_semantic_results_and_syncs_views(tmp_path):
    root = semantic_workspace(tmp_path)
    research.synchronize_derived_artifacts(root)
    data = manifest(root)
    research._atomic_json(root / "semantic-results.json", {
        "concepts": data["concepts"],
        "claims": data["claims"],
        "relations": data["relations"],
    })
    completed = research.complete_compilation(root)
    assert completed["semantic_results_merged"] is True
    assert completed["derived_artifacts"] == {
        "concept_artifacts_changed": 0,
        "claim_artifacts_changed": 0,
        "topic_index_changed": 0,
    }
    assert not (root / "semantic-results.json").exists()


def test_duplicate_concept_ids_are_rejected():
    errors = research.ClaimRegistry.validate({
        "id": "claim-duplicate", "text": "x", "origin": "author",
        "concept_ids": ["alpha", "alpha"], "evidence": [],
    })
    assert "claim concept_ids must not contain duplicates" in errors


def test_mixed_origin_semantics_are_documented():
    schema = (Path(research.__file__).parent.parent / "docs/research-schema.md").read_text(
        encoding="utf-8"
    )
    assert "Multiple sources alone never justify" in schema
    assert not research.ClaimRegistry.validate({
        "id": "claim-mixed", "text": "synthesis", "origin": "mixed", "evidence": []
    })
