"""Research-oriented workspace workflow built on top of book-to-skill extraction.

This module intentionally keeps the first research-to-skill layer deterministic:
it creates a durable research workspace, registers source provenance, extracts clean
text through the existing extractor, and prepares stable directories for later
concept/argument/citation compilation by an agent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from book_to_skill.exceptions import ExtractionError
from book_to_skill.utils import extract_single_file, resolve_input_files

MANIFEST_NAME = "research.json"
SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-._")
    return value or "source"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(root: Path) -> Path:
    return root / MANIFEST_NAME


def _load_manifest(root: Path) -> Dict[str, Any]:
    path = _manifest_path(root)
    if not path.exists():
        raise FileNotFoundError(
            f"No {MANIFEST_NAME} found in {root}. Run 'research-to-skill init <name>' first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(root: Path, manifest: Dict[str, Any]) -> None:
    manifest["updated_at"] = _now_iso()
    _manifest_path(root).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def init_project(name: str, directory: Optional[Path] = None) -> Path:
    root = (directory or Path(name)).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    for relative in (
        "sources/text",
        "sources/meta",
        "concepts",
        "arguments",
        "citations",
        "papers",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)

    manifest_path = _manifest_path(root)
    if manifest_path.exists():
        raise FileExistsError(f"Research workspace already exists: {root}")

    now = _now_iso()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "slug": _slugify(name),
        "created_at": now,
        "updated_at": now,
        "sources": [],
    }
    _save_manifest(root, manifest)

    skill = root / "SKILL.md"
    skill.write_text(
        "---\n"
        f"name: {manifest['slug']}\n"
        f"description: Research skill workspace for {name}.\n"
        "---\n\n"
        f"# {name}\n\n"
        "This workspace is managed by `research-to-skill`.\n\n"
        "## Knowledge layers\n\n"
        "- `sources/`: extracted source text and provenance metadata\n"
        "- `concepts/`: stable concept definitions and evolution\n"
        "- `arguments/`: claims, counterclaims, and argument chains\n"
        "- `citations/`: source-backed citation records\n"
        "- `papers/`: publication-level syntheses\n",
        encoding="utf-8",
    )
    return root


def _unique_source_id(path: Path, digest: str) -> str:
    return f"{_slugify(path.stem)}-{digest[:10]}"


def add_sources(
    root: Path,
    inputs: Iterable[str],
    extraction_mode: str = "text",
    install_mode: str = "no",
) -> List[Dict[str, Any]]:
    root = root.expanduser().resolve()
    manifest = _load_manifest(root)
    files = resolve_input_files(list(inputs))
    if not files:
        raise FileNotFoundError("No supported source files matched the supplied input(s).")

    existing_hashes = {item["sha256"] for item in manifest.get("sources", [])}
    added: List[Dict[str, Any]] = []

    for source in files:
        digest = _sha256(source)
        if digest in existing_hashes:
            continue

        try:
            extracted = extract_single_file(source, extraction_mode, install_mode)
        except ExtractionError as exc:
            print(f"WARNING: skipping {source.name}: {exc}", file=sys.stderr)
            continue

        source_id = _unique_source_id(source, digest)
        text_rel = Path("sources") / "text" / f"{source_id}.txt"
        meta_rel = Path("sources") / "meta" / f"{source_id}.json"
        (root / text_rel).write_text(extracted["text"], encoding="utf-8")

        record = {
            "id": source_id,
            "filename": source.name,
            "source_path": str(source.resolve()),
            "sha256": digest,
            "format": extracted.get("format"),
            "extraction_method": extracted.get("extraction_method"),
            "words": extracted.get("words"),
            "estimated_tokens": extracted.get("estimated_tokens"),
            "chapters_detected": extracted.get("chapters_detected"),
            "has_toc": extracted.get("has_toc"),
            "text_file": text_rel.as_posix(),
            "metadata_file": meta_rel.as_posix(),
            "added_at": _now_iso(),
        }
        (root / meta_rel).write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        manifest.setdefault("sources", []).append(record)
        existing_hashes.add(digest)
        added.append(record)

    _save_manifest(root, manifest)
    return added


def project_status(root: Path) -> Dict[str, Any]:
    root = root.expanduser().resolve()
    manifest = _load_manifest(root)
    sources = manifest.get("sources", [])
    return {
        "name": manifest.get("name"),
        "slug": manifest.get("slug"),
        "root": str(root),
        "source_count": len(sources),
        "total_words": sum(int(item.get("words") or 0) for item in sources),
        "estimated_tokens": sum(int(item.get("estimated_tokens") or 0) for item in sources),
        "updated_at": manifest.get("updated_at"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-to-skill",
        description="Build a provenance-aware, incrementally growing research skill workspace.",
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

    status_cmd = sub.add_parser("status", help="Show research workspace statistics")
    status_cmd.add_argument("--project", type=Path, default=Path.cwd())
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            root = init_project(args.name, args.directory)
            print(f"Initialized research workspace: {root}")
            return 0
        if args.command == "add":
            added = add_sources(args.project, args.inputs, args.mode, args.install_missing)
            print(f"Added {len(added)} new source(s).")
            for item in added:
                print(f"  - {item['id']}: {item['filename']}")
            return 0
        if args.command == "status":
            status = project_status(args.project)
            print(json.dumps(status, ensure_ascii=False, indent=2))
            return 0
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
