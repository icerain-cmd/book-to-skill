# Example research project

The source material in `../sources/` is short, synthetic, and free of third-party
copyrighted text. Generate a disposable project from the repository root:

```bash
research-to-skill init "Example Research" --dir /tmp/example-research
research-to-skill add examples/sources/paper-a.md examples/sources/paper-b.md \
  --project /tmp/example-research
research-to-skill compile --project /tmp/example-research
research-to-skill status --project /tmp/example-research
research-to-skill validate --project /tmp/example-research
```

The compilation plan asks the host agent to preserve the 2024 definition, record
the 2025 revision as a new concept version, distinguish author and external
claims, and link both to source evidence.
