<!-- Thanks for contributing to Selfsame! -->

## What & why

<!-- What does this change and why? -->

## Checklist

- [ ] `PYTHONHASHSEED=0 python -m unittest discover -s tests` passes
- [ ] `ruff check probe tests units` is clean
- [ ] Preserves **zero false confidence** (no false `equivalent`/`divergent`);
      added/updated tests where behavior changed
- [ ] Updated docs / `CHANGELOG.md` if user-facing
- [ ] Branched from and targeting `develop`
