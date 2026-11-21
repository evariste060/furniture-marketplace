# Development product photos

Optional photos for the development catalogue seed (`scripts/seed_development_catalogue.py`).
A file named after a seed product's slug replaces its generated placeholder:

- `<slug>.jpg` (or `.jpeg`, `.png`, `.webp`) is position 1;
- `<slug>__<n>.jpg` is position `n` (2-99).

They go through the real bulk image upload (at most 5 MB each). The slugs are in
`scripts/seed_catalogue_data.py`. Photos are git-ignored: only use images you may use.
