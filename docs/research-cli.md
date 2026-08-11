# Research CLI reference

```text
research-to-skill init NAME [--dir PATH]
research-to-skill add INPUT [INPUT ...] [--project PATH]
                         [--mode text|technical]
                         [--install-missing no|ask|yes]
research-to-skill remove SOURCE_ID [--project PATH] [--cascade]
research-to-skill status [--project PATH]
research-to-skill list [--project PATH]
research-to-skill inspect source|concept|claim ID [--project PATH]
research-to-skill compile [--project PATH]
research-to-skill compile [--project PATH] --complete [SOURCE_ID ...]
research-to-skill validate [--project PATH]
research-to-skill export --format skill|json|markdown
                         [--output PATH] [--project PATH]
```

Commands return zero on success. `add` returns nonzero if every attempted
extraction failed. `validate` returns nonzero when any `ERROR` is present; warnings
alone do not fail. User-facing failures are printed to stderr without a traceback.

`--format skill` creates a ZIP of the complete workspace. JSON exports the
canonical manifest, while Markdown creates a compact portable index. If
`--output` is a directory, a filename based on the project slug is selected.
