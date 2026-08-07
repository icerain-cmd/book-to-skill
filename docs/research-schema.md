# Research schema

`research.json` uses schema version 1 and contains `project`, `sources`,
`concepts`, `claims`, and `relations` arrays plus timestamps.

## Source

Every source has a stable content-derived ID, original filename and absolute
input path, SHA-256, format, extraction method, word/token estimates, nullable
bibliographic metadata, extracted-text and metadata paths, ingestion timestamps,
and incremental compilation fields. Unknown bibliographic metadata stays `null`;
it is never inferred during ingestion.

## Claim and evidence

A claim requires `id`, `text`, and an origin from `author`, `external`, `mixed`,
or `uncertain`. `source_ids` and `concept_ids` are references. Confidence, when
present, is between zero and one.

Evidence records contain a `source_id`, nullable page/section/paragraph locator,
nullable quote, summary, and one of `explicit`, `inferred`, `supporting`, or
`contradicting`. Quotes must be source text, never model reconstructions.

## Concept evolution

A concept stores an ID and append-only `versions`. Each version has a source ID,
date (nullable when unknown), and definition. The current canonical definition
may synthesize versions but must not delete them. Concept Markdown files should
include canonical definition, alternatives, first appearance, evolution, related
concepts, supporting claims, and sources.

## Graph

`relations/knowledge-graph.json` has `nodes` and `edges`. Node types are
`concept`, `claim`, `source`, `author`, and `publication`. Edge types are
`defines`, `supports`, `contradicts`, `extends`, `revises`, `cites`,
`derived_from`, and `related_to`. Both ends of every edge must exist.

## Migration policy

Readers reject unknown schema versions rather than silently reinterpret data.
Future migrations should be explicit, one version at a time, preserve a backup,
and never change stable source IDs or hashes.

During compilation, the host writes a transient `semantic-results.json` object
with `concepts`, `claims`, and `relations` arrays. `compile --complete` validates
and merges those arrays into `research.json`; the proposal is not canonical.
