# Research-to-Skill guide

`research-to-skill` turns a growing collection of papers, books, notes, and
reports into auditable research memory. It is additive: the original
`book-to-skill` command and workflow remain unchanged.

## Quick start

```bash
research-to-skill init "My Research" --dir ./my-research
research-to-skill add ./papers ./books ./notes --project ./my-research
research-to-skill status --project ./my-research
research-to-skill compile --project ./my-research
research-to-skill validate --project ./my-research
```

`add` recursively resolves supported files through the existing extraction
pipeline. Identical content is skipped by SHA-256, including a renamed copy.
Failures are reported per file and do not discard successful files from a batch.

## Commands

| Command | Purpose |
| --- | --- |
| `init NAME [--dir PATH]` | Create a canonical research workspace. |
| `add INPUT... [--project PATH]` | Extract and register one or more sources. |
| `remove ID [--cascade]` | Remove a source; block when artifacts depend on it. |
| `status` | Show corpus totals and dirty-source count. |
| `list` | List registered sources and hashes. |
| `inspect {source,concept,claim} ID` | Print a record as JSON. |
| `compile` | Write a provider-independent incremental compilation plan. |
| `validate` | Report `PASS`, `WARN`, and `ERROR` integrity findings. |
| `export --format {skill,json,markdown}` | Export a ZIP skill or portable view. |

All commands except `init` accept `--project`; it defaults to the current
directory. Use `--mode technical` for structure-heavy documents and
`--install-missing ask|yes|no` to control optional extractor installation.

## Semantic compilation

`compile` does not call an LLM. It writes `compile-plan.json` containing only
sources whose current hash differs from `compiled_hash`. A compatible host agent
reads that plan and the generated `SKILL.md`, then creates or merges concepts,
claims, arguments, papers, and graph records. This keeps provider choice outside
the deterministic data layer.

After the host has written artifacts and `validate` reports no errors, it runs
`compile --complete SOURCE_ID...` to atomically record compiled hashes and advance
semantic versions. Omitting IDs finalizes all registered sources.

The retrieval order is concepts → claims → arguments → papers → sources. The
agent descends to source text only when it needs evidence, a locator, or conflict
resolution.

## Safe removal

`remove SOURCE_ID` refuses to proceed when claims, concepts, arguments,
citations, or paper records depend on the source. `--cascade` is explicit and
also removes dependent graph nodes and edges. Back up or export the workspace
before a cascade removal.

## Attribution

This research extension is maintained in a transparent fork of
`virgiliojr94/book-to-skill`. The upstream attribution and MIT license remain in
place. Source documents and generated research data retain their own copyrights.
