# Research architecture

## Two layers

The boundary is deliberate:

```text
source files
    │
    ▼
deterministic ingestion (Python)
files · extraction · SHA-256 · IDs · provenance · manifest · validation
    │
    ▼
compile-plan.json
    │
    ▼
semantic compilation (host agent)
concepts · claims · identity · evolution · arguments · synthesis
```

Python is authoritative for source identity and storage. A host agent must not
rewrite hashes, IDs, paths, or provenance. The host may write semantic artifacts
only from registered sources and must retain evidence links.

## Components

- `ResearchProject` creates and loads the workspace.
- `SourceRegistry` performs deterministic ingestion and deduplication.
- `ClaimRegistry` and `ConceptRegistry` validate semantic record shapes.
- `KnowledgeGraph` checks node and edge types and dangling references.
- `Compiler` emits an incremental, provider-independent work plan.
- `Validator` checks referential, file, graph, and Agent Skills integrity.

`research.json` is the single source of truth. Per-source metadata files are
portable provenance snapshots; they do not supersede the manifest.

## Consistency and failure behavior

JSON and text are written to a sibling temporary file, flushed, then atomically
replaced. A failed source in a batch becomes a warning while successful sources
are committed. Manifest parsing fails closed on malformed JSON or unsupported
schema versions. Stored paths are resolved and rejected if they leave the project
root.

## Incrementality

Each source stores `sha256`, `compiled_hash`, `compiled_at`, `compiler_version`,
and `semantic_version`. A new or changed hash is dirty. `compile` lists dirty
sources and existing semantic IDs so a host can merge only affected knowledge.
The host writes a `semantic-results.json` proposal and rendered artifacts, then
uses `compile --complete`. Python validates and merges the proposal into the
canonical manifest, records compiled hashes, and advances semantic versions. The
agent therefore never edits canonical provenance directly.

## Extension points

Nullable source fields (`authors`, `title`, `year`, `doi`, `url`) allow future
metadata adapters without guessing. The JSON graph can later be translated to
JSON-LD, GraphRAG, Neo4j, or HEGI while keeping source and claim IDs stable.
