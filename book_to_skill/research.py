"""Deterministic storage and CLI for persistent research skills.

Semantic interpretation is intentionally left to a host agent.  This module owns
only files, hashes, identifiers, provenance, schemas, dependency checks and plans.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from book_to_skill.exceptions import ExtractionError
from book_to_skill.utils import extract_single_file, resolve_input_files

MANIFEST_NAME = "research.json"
SCHEMA_VERSION = 1
COMPILER_VERSION = "1"
CLAIM_ORIGINS = {"author", "external", "mixed", "uncertain"}
EVIDENCE_TYPES = {"explicit", "inferred", "supporting", "contradicting"}
NODE_TYPES = {"concept", "claim", "source", "author", "publication"}
EDGE_TYPES = {
    "defines", "supports", "contradicts", "extends", "revises", "cites",
    "derived_from", "related_to",
}
PROJECT_DIRS = (
    "sources/text", "sources/meta", "sources/raw-index", "concepts", "arguments",
    "claims", "citations", "relations", "papers",
)


class ResearchError(Exception):
    """A user-facing research workspace error."""


class ManifestError(ResearchError):
    """The canonical manifest cannot be read or validated."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-._") or "research"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _manifest_path(root: Path) -> Path:
    return root / MANIFEST_NAME


def _validate_manifest_shape(manifest: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(manifest, dict):
        return ["manifest root must be an object"]
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {manifest.get('schema_version')!r}")
    project = manifest.get("project")
    if not isinstance(project, dict) or not project.get("name") or not project.get("slug"):
        errors.append("project.name and project.slug are required")
    elif project["slug"] != _slugify(str(project["slug"])):
        errors.append("project.slug must be a canonical filename-safe slug")
    for key in ("sources", "concepts", "claims", "relations"):
        if not isinstance(manifest.get(key), list):
            errors.append(f"{key} must be an array")
    return errors


def _load_manifest(root: Path) -> Dict[str, Any]:
    path = _manifest_path(root)
    if not path.is_file():
        raise ManifestError(
            f"No {MANIFEST_NAME} found in {root}. Run 'research-to-skill init <name>' first."
        )
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"Cannot read {path}: {exc}") from exc
    errors = _validate_manifest_shape(manifest)
    if errors:
        raise ManifestError("Invalid research.json: " + "; ".join(errors))
    return manifest


def _save_manifest(root: Path, manifest: Dict[str, Any]) -> None:
    manifest["updated_at"] = _now_iso()
    _atomic_json(_manifest_path(root), manifest)


def _safe_project_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ManifestError(f"path escapes project root: {relative!r}") from exc
    return candidate


def _skill_text(name: str, slug: str) -> str:
    return f"""---
name: {slug}
description: Provenance-aware research memory for {name}; use it to answer questions about this corpus's concepts, claims, arguments, evolution, and sources.
---

# {name}

This is a persistent research skill managed by `research-to-skill`. Semantic
artifacts are compiled by the host agent from deterministic source records.

## Retrieval order

Read only the smallest useful layer, in this order:

1. `concepts/` for definitions, alternatives, and evolution.
2. `claims/` for atomic claims and provenance.
3. `arguments/` for theses, premises, counterarguments, and limitations.
4. `papers/` for publication-level contributions and chronology.
5. `sources/` only to verify evidence or resolve ambiguity.

For relationships, consult `relations/knowledge-graph.json`. Use `topic-index.md`,
`timeline.md`, `glossary.md`, and `bibliography.md` to narrow retrieval.

## Citation-safe rules

- Never invent a claim, citation, locator, quote, author, title, year, or DOI.
- Distinguish the researcher's claims (`author`) from cited scholarship
  (`external`); preserve `mixed` and `uncertain` when attribution is unclear.
- Trace substantive answers through claim evidence to a source. Say when evidence
  or attribution is missing.
- Treat concept summaries as indexes, never as stronger evidence than sources.
- Surface contradictions and limitations. Do not silently choose one account.
- Preserve historical definitions; a new definition does not erase an old one.
- Do not edit source hashes, IDs, provenance, or `research.json` during semantic
  compilation. Write generated artifacts and a `semantic-results.json` bundle
  described by `compile-plan.json`; finalization merges it deterministically.

## Incremental semantic compilation

Run `research-to-skill compile --project <path>`, then read
`compile-plan.json`. Process only its dirty sources. Merge findings into existing
artifacts without overwriting earlier concept versions or unsupported claims.
Every claim must use an allowed origin and should carry source-backed evidence.
Write `semantic-results.json` with `concepts`, `claims`, and `relations` arrays.
After writing artifacts, run `research-to-skill validate --project <path>`.
If validation has no errors, finalize the processed hashes with
`research-to-skill compile --project <path> --complete <source-id>...`.
"""


def _empty_manifest(name: str) -> Dict[str, Any]:
    now = _now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "project": {"name": name, "slug": _slugify(name)},
        "sources": [], "concepts": [], "claims": [], "relations": [],
        "created_at": now, "updated_at": now,
    }


class ResearchProject:
    """Small library API around the canonical manifest."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()

    @classmethod
    def create(cls, name: str, directory: Optional[Path] = None) -> "ResearchProject":
        if not name.strip():
            raise ResearchError("Project name cannot be empty.")
        root = (directory or Path(_slugify(name))).expanduser().resolve()
        if _manifest_path(root).exists():
            raise FileExistsError(f"Research workspace already exists: {root}")
        if root.exists() and any(root.iterdir()):
            raise FileExistsError(f"Refusing to initialize a non-empty directory: {root}")
        root.mkdir(parents=True, exist_ok=True)
        for relative in PROJECT_DIRS:
            (root / relative).mkdir(parents=True, exist_ok=True)
        manifest = _empty_manifest(name.strip())
        _save_manifest(root, manifest)
        _atomic_text(root / "SKILL.md", _skill_text(name.strip(), manifest["project"]["slug"]))
        _atomic_json(root / "relations" / "knowledge-graph.json", {"nodes": [], "edges": []})
        for filename, heading in (
            ("glossary.md", "Glossary"), ("timeline.md", "Research Timeline"),
            ("topic-index.md", "Topic Index"), ("bibliography.md", "Bibliography"),
        ):
            _atomic_text(root / filename, f"# {heading}\n\n_Not compiled yet._\n")
        return cls(root)

    @property
    def manifest(self) -> Dict[str, Any]:
        return _load_manifest(self.root)


def init_project(name: str, directory: Optional[Path] = None) -> Path:
    return ResearchProject.create(name, directory).root


def _unique_source_id(path: Path, digest: str, existing: Sequence[str]) -> str:
    base = f"{_slugify(path.stem)}-{digest[:10]}"
    if base not in existing:
        return base
    for length in range(12, 65, 2):
        candidate = f"{_slugify(path.stem)}-{digest[:length]}"
        if candidate not in existing:
            return candidate
    raise ResearchError(f"Cannot allocate a unique source ID for {path}")


class SourceRegistry:
    def __init__(self, project: ResearchProject):
        self.project = project

    def add(
        self, inputs: Iterable[str], extraction_mode: str = "text", install_mode: str = "no"
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
        manifest = self.project.manifest
        files = resolve_input_files(list(inputs))
        if not files:
            raise FileNotFoundError("No supported source files matched the supplied input(s).")
        hashes = {item.get("sha256") for item in manifest["sources"]}
        ids = [str(item.get("id")) for item in manifest["sources"]]
        added: List[Dict[str, Any]] = []
        failures: List[Dict[str, str]] = []
        for source in files:
            try:
                digest = _sha256(source)
                if digest in hashes:
                    continue
                extracted = extract_single_file(source, extraction_mode, install_mode)
                text = str(extracted.get("text") or "")
                if not text.strip():
                    raise ExtractionError("extraction produced no text")
                source_id = _unique_source_id(source, digest, ids)
                text_rel = f"sources/text/{source_id}.txt"
                meta_rel = f"sources/meta/{source_id}.json"
                now = _now_iso()
                record = {
                    "id": source_id, "filename": source.name,
                    "source_path": str(source.resolve()), "sha256": digest,
                    "format": extracted.get("format") or source.suffix.lower().lstrip("."),
                    "extraction_method": extracted.get("extraction_method"),
                    "words": int(extracted.get("words") or 0),
                    "estimated_tokens": int(extracted.get("estimated_tokens") or 0),
                    "authors": [], "title": None, "year": None, "doi": None, "url": None,
                    "text_file": text_rel, "metadata_file": meta_rel,
                    "added_at": now, "updated_at": now,
                    "compiled_hash": None, "compiled_at": None,
                    "compiler_version": None, "semantic_version": 0,
                }
                try:
                    _atomic_text(self.project.root / text_rel, text)
                    _atomic_json(self.project.root / meta_rel, record)
                except BaseException:
                    for relative in (text_rel, meta_rel):
                        path = self.project.root / relative
                        if path.is_file():
                            path.unlink()
                    raise
                manifest["sources"].append(record)
                hashes.add(digest)
                ids.append(source_id)
                added.append(record)
            except (ExtractionError, OSError, UnicodeError, ValueError) as exc:
                failures.append({"path": str(source), "error": str(exc)})
        if added:
            try:
                _save_manifest(self.project.root, manifest)
            except BaseException:
                for record in added:
                    for key in ("text_file", "metadata_file"):
                        path = self.project.root / record[key]
                        if path.is_file():
                            path.unlink()
                raise
        return added, failures


def add_sources(
    root: Path, inputs: Iterable[str], extraction_mode: str = "text", install_mode: str = "no"
) -> List[Dict[str, Any]]:
    added, failures = SourceRegistry(ResearchProject(root)).add(
        inputs, extraction_mode, install_mode
    )
    for failure in failures:
        print(f"WARNING: skipping {failure['path']}: {failure['error']}", file=sys.stderr)
    return added


def project_status(root: Path) -> Dict[str, Any]:
    project = ResearchProject(root)
    manifest = project.manifest
    sources = manifest["sources"]
    dirty = sum(1 for item in sources if item.get("compiled_hash") != item.get("sha256"))
    return {
        "name": manifest["project"]["name"], "slug": manifest["project"]["slug"],
        "root": str(project.root), "source_count": len(sources),
        "total_words": sum(int(item.get("words") or 0) for item in sources),
        "estimated_tokens": sum(int(item.get("estimated_tokens") or 0) for item in sources),
        "concept_count": len(manifest["concepts"]), "claim_count": len(manifest["claims"]),
        "dirty_source_count": dirty, "updated_at": manifest.get("updated_at"),
    }


def list_sources(root: Path) -> List[Dict[str, Any]]:
    return [
        {key: item.get(key) for key in ("id", "filename", "format", "words", "sha256")}
        for item in ResearchProject(root).manifest["sources"]
    ]


def _load_json_artifact(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResearchError(f"Expected a JSON object in {path}")
    return value


def inspect_item(root: Path, kind: str, item_id: str) -> Dict[str, Any]:
    project = ResearchProject(root)
    manifest = project.manifest
    if kind == "source":
        items = manifest["sources"]
    elif kind == "claim":
        items = manifest["claims"]
    elif kind == "concept":
        items = manifest["concepts"]
    else:
        raise ResearchError(f"Unsupported inspect type: {kind}")
    item = next((entry for entry in items if entry.get("id") == item_id), None)
    if item is None:
        raise ResearchError(f"Unknown {kind} ID: {item_id}")
    # research.json is canonical. Artifact files may be richer renderings, but
    # inspect must never return an older metadata snapshot instead of manifest state.
    if kind == "source":
        return dict(item)
    file_ref = item.get("file")
    if file_ref:
        path = _safe_project_path(project.root, str(file_ref))
        if path.suffix == ".json" and path.is_file():
            return _load_json_artifact(path)
    return dict(item)


def _artifact_dependencies(root: Path, source_id: str) -> List[Tuple[str, str]]:
    manifest = ResearchProject(root).manifest
    dependencies: List[Tuple[str, str]] = []
    for kind in ("claims", "concepts"):
        for item in manifest[kind]:
            refs = set(item.get("source_ids") or [])
            refs.update(v.get("source_id") for v in item.get("versions", []) if isinstance(v, dict))
            if source_id in refs:
                dependencies.append((kind[:-1], str(item.get("id"))))
    for folder in ("arguments", "citations", "papers"):
        for path in (root / folder).glob("*"):
            if not path.is_file():
                continue
            if path.suffix == ".json":
                data = _load_json_artifact(path)
                referenced = (
                    source_id in (data.get("source_ids") or [])
                    or data.get("source_id") == source_id
                )
            else:
                try:
                    referenced = source_id in path.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    referenced = False
            if referenced:
                dependencies.append((folder[:-1], path.name))
    return dependencies


def remove_source(root: Path, source_id: str, cascade: bool = False) -> List[str]:
    project = ResearchProject(root)
    manifest = project.manifest
    source = next((item for item in manifest["sources"] if item.get("id") == source_id), None)
    if source is None:
        raise ResearchError(f"Unknown source ID: {source_id}")
    dependencies = _artifact_dependencies(project.root, source_id)
    if dependencies and not cascade:
        rendered = ", ".join(f"{kind}:{ident}" for kind, ident in dependencies)
        raise ResearchError(f"Removal blocked; dependent artifacts exist: {rendered}. Use --cascade.")
    removed = [source_id]
    removal_paths: List[Path] = []
    graph_update: Optional[Tuple[Path, Dict[str, Any]]] = None
    if cascade:
        dependent_claims = {
            item["id"] for item in manifest["claims"] if source_id in (item.get("source_ids") or [])
        }
        dependent_concepts = {
            item["id"] for item in manifest["concepts"]
            if source_id in (item.get("source_ids") or [])
            or any(v.get("source_id") == source_id for v in item.get("versions", []) if isinstance(v, dict))
        }
        manifest["claims"] = [item for item in manifest["claims"] if item.get("id") not in dependent_claims]
        manifest["concepts"] = [
            item for item in manifest["concepts"]
            if source_id not in (item.get("source_ids") or [])
            and not any(v.get("source_id") == source_id for v in item.get("versions", []) if isinstance(v, dict))
        ]
        for kind, identifier in dependencies:
            if kind in {"argument", "citation", "paper"}:
                path = _safe_project_path(project.root, f"{kind}s/{identifier}")
                if path.is_file():
                    removal_paths.append(path)
                    removed.append(path.relative_to(project.root).as_posix())
        for folder in ("claims", "arguments", "citations", "papers"):
            for path in (project.root / folder).glob("*.json"):
                try:
                    data = _load_json_artifact(path)
                except ResearchError:
                    continue
                if (
                    source_id in (data.get("source_ids") or [])
                    or data.get("source_id") == source_id
                    or data.get("id") in dependent_claims
                ):
                    removal_paths.append(path)
                    removed.append(path.relative_to(project.root).as_posix())
        graph_path = project.root / "relations" / "knowledge-graph.json"
        graph = _load_json_artifact(graph_path)
        removed_nodes = {source_id, *dependent_claims, *dependent_concepts}
        graph["nodes"] = [node for node in graph.get("nodes", []) if node.get("id") not in removed_nodes]
        graph["edges"] = [
            edge for edge in graph.get("edges", [])
            if edge.get("source") not in removed_nodes and edge.get("target") not in removed_nodes
        ]
        graph_update = (graph_path, graph)
    for key in ("text_file", "metadata_file"):
        if source.get(key):
            path = _safe_project_path(project.root, str(source[key]))
            if path.is_file():
                removal_paths.append(path)
    manifest["sources"] = [item for item in manifest["sources"] if item.get("id") != source_id]
    # Commit canonical metadata first. Cleanup failures can then leave only
    # recoverable orphan files, never live records pointing at deleted data.
    _save_manifest(project.root, manifest)
    if graph_update:
        _atomic_json(*graph_update)
    for path in dict.fromkeys(removal_paths):
        if path.is_file():
            path.unlink()
    return removed


class ClaimRegistry:
    @staticmethod
    def validate(claim: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        if not claim.get("id") or not claim.get("text"):
            errors.append("claim id and text are required")
        if claim.get("origin") not in CLAIM_ORIGINS:
            errors.append(f"invalid claim origin: {claim.get('origin')!r}")
        confidence = claim.get("confidence")
        if confidence is not None and (not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
            errors.append("claim confidence must be between 0 and 1")
        for evidence in claim.get("evidence", []):
            if not isinstance(evidence, dict) or evidence.get("evidence_type") not in EVIDENCE_TYPES:
                errors.append("invalid evidence_type")
        return errors


class ConceptRegistry:
    @staticmethod
    def validate(concept: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        if not concept.get("id"):
            errors.append("concept id is required")
        for version in concept.get("versions", []):
            if not isinstance(version, dict) or not version.get("source_id"):
                errors.append("concept versions require source_id")
        return errors


class KnowledgeGraph:
    @staticmethod
    def validate(graph: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return ["graph nodes and edges must be arrays"]
        node_ids = {node.get("id") for node in nodes if isinstance(node, dict)}
        for node in nodes:
            if not isinstance(node, dict) or node.get("type") not in NODE_TYPES:
                errors.append(f"invalid graph node: {node!r}")
        for edge in edges:
            if not isinstance(edge, dict) or edge.get("type") not in EDGE_TYPES:
                errors.append(f"invalid graph edge: {edge!r}")
            elif edge.get("source") not in node_ids or edge.get("target") not in node_ids:
                errors.append(f"dangling graph edge: {edge.get('source')} -> {edge.get('target')}")
        return errors


class Compiler:
    def __init__(self, project: ResearchProject):
        self.project = project

    def plan(self) -> Dict[str, Any]:
        manifest = self.project.manifest
        dirty = [s for s in manifest["sources"] if s.get("compiled_hash") != s.get("sha256")]
        plan = {
            "schema_version": 1, "compiler_version": COMPILER_VERSION,
            "generated_at": _now_iso(), "mode": "incremental",
            "dirty_sources": [
                {"id": s["id"], "sha256": s["sha256"], "text_file": s["text_file"]}
                for s in dirty
            ],
            "existing_artifacts": {
                "concept_ids": [item.get("id") for item in manifest["concepts"]],
                "claim_ids": [item.get("id") for item in manifest["claims"]],
            },
            "instructions": [
                "Read SKILL.md citation-safe rules before semantic compilation.",
                "Process only dirty_sources and merge; never erase historical concept versions.",
                "Do not modify source IDs, hashes, provenance, or extracted source text.",
                "Validate claim origins, evidence locators, and graph references before completion.",
                "Write semantic-results.json with concepts, claims, and relations arrays.",
            ],
            "status": "semantic-compilation-required" if dirty else "up-to-date",
        }
        _atomic_json(self.project.root / "compile-plan.json", plan)
        return plan

    def complete(self, source_ids: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        findings = Validator(self.project).run()
        errors = [item for item in findings if item["level"] == "ERROR"]
        if errors:
            raise ResearchError("Cannot finalize compilation while validation errors exist.")
        manifest = self.project.manifest
        results_path = self.project.root / "semantic-results.json"
        if results_path.is_file():
            results = _load_json_artifact(results_path)
            for key, validator in (
                ("concepts", ConceptRegistry.validate), ("claims", ClaimRegistry.validate)
            ):
                values = results.get(key, [])
                if not isinstance(values, list):
                    raise ResearchError(f"semantic-results.json {key} must be an array")
                messages = [message for item in values for message in validator(item)]
                if messages:
                    raise ResearchError(f"Invalid semantic {key}: " + "; ".join(messages))
                merged = {item["id"]: item for item in manifest[key]}
                merged.update({item["id"]: item for item in values})
                manifest[key] = list(merged.values())
            relations = results.get("relations", [])
            if not isinstance(relations, list):
                raise ResearchError("semantic-results.json relations must be an array")
            manifest["relations"] = relations
            source_refs = {item["id"] for item in manifest["sources"]}
            concept_refs = {item["id"] for item in manifest["concepts"]}
            for concept in manifest["concepts"]:
                refs = [v.get("source_id") for v in concept.get("versions", []) if isinstance(v, dict)]
                if any(ref not in source_refs for ref in refs):
                    raise ResearchError(f"Concept {concept['id']} has an unknown source reference")
            for claim in manifest["claims"]:
                refs = list(claim.get("source_ids") or [])
                refs.extend(
                    e.get("source_id") for e in claim.get("evidence", []) if isinstance(e, dict)
                )
                if any(ref not in source_refs for ref in refs):
                    raise ResearchError(f"Claim {claim['id']} has an unknown source reference")
                if any(ref not in concept_refs for ref in claim.get("concept_ids") or []):
                    raise ResearchError(f"Claim {claim['id']} has an unknown concept reference")
        known = {item["id"] for item in manifest["sources"]}
        selected = set(source_ids or known)
        unknown = selected - known
        if unknown:
            raise ResearchError("Unknown source ID(s): " + ", ".join(sorted(unknown)))
        now = _now_iso()
        completed = []
        for source in manifest["sources"]:
            if source["id"] not in selected:
                continue
            source["compiled_hash"] = source["sha256"]
            source["compiled_at"] = now
            source["compiler_version"] = COMPILER_VERSION
            source["semantic_version"] = int(source.get("semantic_version") or 0) + 1
            _atomic_json(self.project.root / source["metadata_file"], source)
            completed.append(source["id"])
        _save_manifest(self.project.root, manifest)
        return {
            "completed_sources": completed, "compiled_at": now,
            "semantic_results_merged": results_path.is_file(),
        }


def compile_project(root: Path) -> Dict[str, Any]:
    return Compiler(ResearchProject(root)).plan()


def complete_compilation(root: Path, source_ids: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    return Compiler(ResearchProject(root)).complete(source_ids)


class Validator:
    def __init__(self, project: ResearchProject):
        self.project = project

    def run(self) -> List[Dict[str, str]]:
        findings: List[Dict[str, str]] = []
        try:
            manifest = self.project.manifest
        except ManifestError as exc:
            return [{"level": "ERROR", "code": "invalid-manifest", "message": str(exc)}]

        def add(level: str, code: str, message: str) -> None:
            findings.append({"level": level, "code": code, "message": message})

        all_ids: List[str] = []
        for kind in ("sources", "concepts", "claims"):
            ids = [str(item.get("id")) for item in manifest[kind] if isinstance(item, dict)]
            all_ids.extend(ids)
            duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
            for item_id in duplicates:
                add("ERROR", "duplicate-id", f"duplicate {kind} ID: {item_id}")
        for item_id in sorted({item_id for item_id in all_ids if all_ids.count(item_id) > 1}):
            add("ERROR", "duplicate-id", f"ID is reused across artifact types: {item_id}")
        source_ids = {item.get("id") for item in manifest["sources"]}
        concept_ids = {item.get("id") for item in manifest["concepts"]}
        for source in manifest["sources"]:
            for key in ("text_file", "metadata_file"):
                try:
                    path = _safe_project_path(self.project.root, str(source.get(key) or ""))
                except ManifestError as exc:
                    add("ERROR", "unsafe-path", str(exc))
                    continue
                if not path.is_file():
                    add("ERROR", "missing-file", f"{source.get('id')} missing {key}: {path}")
            if source.get("compiled_hash") != source.get("sha256"):
                add("WARN", "stale-artifact", f"source {source.get('id')} needs semantic compilation")
        for claim in manifest["claims"]:
            for message in ClaimRegistry.validate(claim):
                add("ERROR", "invalid-claim", f"{claim.get('id')}: {message}")
            refs = claim.get("source_ids") or []
            if not refs:
                add("WARN", "orphan-claim", f"claim {claim.get('id')} has no source")
            for ref in refs:
                if ref not in source_ids:
                    add("ERROR", "broken-source-ref", f"claim {claim.get('id')} -> {ref}")
            if not claim.get("evidence"):
                add("WARN", "missing-evidence", f"claim {claim.get('id')} has no evidence")
            for evidence in claim.get("evidence") or []:
                if isinstance(evidence, dict) and evidence.get("source_id") not in source_ids:
                    add(
                        "ERROR", "broken-source-ref",
                        f"claim {claim.get('id')} evidence -> {evidence.get('source_id')}",
                    )
            for ref in claim.get("concept_ids") or []:
                if ref not in concept_ids:
                    add("ERROR", "missing-concept-ref", f"claim {claim.get('id')} -> {ref}")
        for concept in manifest["concepts"]:
            for message in ConceptRegistry.validate(concept):
                add("ERROR", "invalid-concept", f"{concept.get('id')}: {message}")
            for version in concept.get("versions", []):
                if isinstance(version, dict) and version.get("source_id") not in source_ids:
                    add("ERROR", "broken-source-ref", f"concept {concept.get('id')} -> {version.get('source_id')}")
        graph_path = self.project.root / "relations" / "knowledge-graph.json"
        try:
            for message in KnowledgeGraph.validate(_load_json_artifact(graph_path)):
                add("ERROR", "invalid-graph", message)
        except ResearchError as exc:
            add("ERROR", "invalid-graph", str(exc))
        skill_path = self.project.root / "SKILL.md"
        try:
            skill = skill_path.read_text(encoding="utf-8")
            if not re.match(r"^---\n.*?\n---\n", skill, re.DOTALL):
                add("ERROR", "malformed-frontmatter", "SKILL.md frontmatter is missing or malformed")
            for key in ("name:", "description:"):
                if key not in skill.split("---", 2)[1]:
                    add("ERROR", "agent-skill", f"SKILL.md frontmatter missing {key[:-1]}")
        except (OSError, UnicodeError) as exc:
            add("ERROR", "agent-skill", f"Cannot read SKILL.md: {exc}")
        if not findings:
            add("PASS", "workspace", "workspace is valid and up to date")
        elif not any(item["level"] == "ERROR" for item in findings):
            add("PASS", "structure", "no structural errors found")
        return findings


def validate_project(root: Path) -> List[Dict[str, str]]:
    return Validator(ResearchProject(root)).run()


def export_project(root: Path, export_format: str, output: Optional[Path] = None) -> Path:
    project = ResearchProject(root)
    manifest = project.manifest
    output = output.expanduser().resolve() if output else project.root.parent.resolve()
    if export_format == "skill":
        target = output if output.suffix == ".zip" else output / f"{manifest['project']['slug']}-skill.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(suffix=".zip", dir=str(target.parent))
        os.close(fd)
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(project.root.rglob("*")):
                    # Never dereference links outside the workspace or include the
                    # archive while it is being built inside the project.
                    if path.is_symlink() or not path.is_file():
                        continue
                    if path.resolve() in {Path(temporary).resolve(), target.resolve()}:
                        continue
                    archive.write(path, path.relative_to(project.root))
            os.replace(temporary, target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return target
    if export_format == "json":
        target = output if output.suffix == ".json" else output / f"{manifest['project']['slug']}.json"
        _atomic_json(target, manifest)
        return target
    target = output if output.suffix == ".md" else output / f"{manifest['project']['slug']}.md"
    sections = [f"# {manifest['project']['name']}", "", "## Sources", ""]
    sections.extend(f"- `{s['id']}` — {s['filename']}" for s in manifest["sources"])
    sections.extend(["", "## Concepts", ""])
    sections.extend(f"- `{c.get('id')}`" for c in manifest["concepts"])
    sections.extend(["", "## Claims", ""])
    sections.extend(f"- **{c.get('origin')}**: {c.get('text')}" for c in manifest["claims"])
    _atomic_text(target, "\n".join(sections) + "\n")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-to-skill",
        description="Build a provenance-aware, incrementally growing research skill.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    init_cmd = sub.add_parser("init", help="Create a research skill workspace")
    init_cmd.add_argument("name")
    init_cmd.add_argument("--dir", dest="directory", type=Path)
    add_cmd = sub.add_parser("add", help="Extract and register research sources")
    add_cmd.add_argument("inputs", nargs="+")
    add_cmd.add_argument("--project", type=Path, default=Path.cwd())
    add_cmd.add_argument("--mode", choices=("technical", "text"), default="text")
    add_cmd.add_argument("--install-missing", choices=("ask", "yes", "no"), default="no")
    remove_cmd = sub.add_parser("remove", help="Remove a source safely")
    remove_cmd.add_argument("source_id")
    remove_cmd.add_argument("--project", type=Path, default=Path.cwd())
    remove_cmd.add_argument("--cascade", action="store_true")
    for command, help_text in (("status", "Show workspace statistics"), ("list", "List sources")):
        cmd = sub.add_parser(command, help=help_text)
        cmd.add_argument("--project", type=Path, default=Path.cwd())
    inspect_cmd = sub.add_parser("inspect", help="Inspect a source, concept, or claim")
    inspect_cmd.add_argument("kind", choices=("source", "concept", "claim"))
    inspect_cmd.add_argument("id")
    inspect_cmd.add_argument("--project", type=Path, default=Path.cwd())
    for command, help_text in (("compile", "Create an incremental semantic compilation plan"), ("validate", "Validate workspace integrity")):
        cmd = sub.add_parser(command, help=help_text)
        cmd.add_argument("--project", type=Path, default=Path.cwd())
        if command == "compile":
            cmd.add_argument(
                "--complete", nargs="*", metavar="SOURCE_ID",
                help="Finalize validated semantic compilation (all dirty sources if IDs omitted)",
            )
    export_cmd = sub.add_parser("export", help="Export the research workspace")
    export_cmd.add_argument("--format", choices=("skill", "json", "markdown"), required=True)
    export_cmd.add_argument("--output", type=Path)
    export_cmd.add_argument("--project", type=Path, default=Path.cwd())
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            print(f"Initialized research workspace: {init_project(args.name, args.directory)}")
        elif args.command == "add":
            added, failures = SourceRegistry(ResearchProject(args.project)).add(
                args.inputs, args.mode, args.install_missing
            )
            print(f"Added {len(added)} new source(s).")
            for item in added:
                print(f"  - {item['id']}: {item['filename']}")
            for failure in failures:
                print(f"WARNING: skipping {failure['path']}: {failure['error']}", file=sys.stderr)
            if failures and not added:
                return 1
        elif args.command == "remove":
            removed = remove_source(args.project, args.source_id, args.cascade)
            print(f"Removed {len(removed)} item(s): {', '.join(removed)}")
        elif args.command == "status":
            print(json.dumps(project_status(args.project), ensure_ascii=False, indent=2))
        elif args.command == "list":
            print(json.dumps(list_sources(args.project), ensure_ascii=False, indent=2))
        elif args.command == "inspect":
            print(json.dumps(inspect_item(args.project, args.kind, args.id), ensure_ascii=False, indent=2))
        elif args.command == "compile":
            result = (
                complete_compilation(args.project, args.complete)
                if args.complete is not None else compile_project(args.project)
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "validate":
            findings = validate_project(args.project)
            for finding in findings:
                print(f"{finding['level']} [{finding['code']}] {finding['message']}")
            return 1 if any(item["level"] == "ERROR" for item in findings) else 0
        elif args.command == "export":
            print(f"Exported: {export_project(args.project, args.format, args.output)}")
        return 0
    except (ResearchError, FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
