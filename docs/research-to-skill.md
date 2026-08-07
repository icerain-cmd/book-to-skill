# research-to-skill MVP

`research-to-skill` extends book-to-skill from one-shot document conversion into an incrementally growing, provenance-aware research workspace.

## Design goals

1. Preserve upstream `book-to-skill` behavior and file formats.
2. Reuse the existing deterministic extraction layer instead of duplicating parsers.
3. Treat research as a long-lived corpus: sources can be added over time and duplicate files are ignored by SHA-256.
4. Keep provenance next to extracted text so later concept, argument, and citation synthesis can point back to an exact source.
5. Separate deterministic ingestion from agent-driven synthesis.

## Commands

```bash
research-to-skill init "Mechanocene Research" --dir ./mechanocene-research
research-to-skill add ./papers/*.pdf --project ./mechanocene-research
research-to-skill status --project ./mechanocene-research
```

For technical PDFs with tables, formulas, or complex layouts:

```bash
research-to-skill add paper.pdf \
  --project ./mechanocene-research \
  --mode technical \
  --install-missing ask
```

## Workspace layout

```text
mechanocene-research/
├── SKILL.md
├── research.json
├── sources/
│   ├── text/          # deterministic extracted text
│   └── meta/          # one provenance record per source
├── concepts/          # phase 2: concept definitions + evolution
├── arguments/         # phase 2: claims/counterclaims + evidence
├── citations/         # phase 2: source-backed citation records
└── papers/            # phase 2: publication-level syntheses
```

`research.json` is the canonical project manifest. Each source record includes the original path, SHA-256 digest, extraction method, format, word/token estimates, structure metadata, and the paths of its extracted text and provenance record.

## Why this layer is separate from book-to-skill

The upstream project already handles multi-source extraction, but its primary output is a generated skill for a bounded input set. Research projects have additional lifecycle requirements:

- new material arrives continuously;
- the same paper must not be ingested twice;
- source identity and provenance must survive later synthesis;
- concepts may change meaning across publications and time;
- the researcher's own claims must eventually be distinguishable from claims in external literature.

The MVP solves the ingestion and persistence portion first. It intentionally does not ask an LLM to invent concept files during `add`.

## Next compiler layer

The next phase should add an explicit `compile` command that reads only registered source text and produces structured records such as:

```text
concepts/mechanocene.md
arguments/algorithmic-environment.md
citations/<source-id>.json
papers/<paper-id>.md
```

Each generated claim should retain source IDs and evidence locations. A later HEGI adapter can then route queries between the local Research Skill and external scholarly search.
