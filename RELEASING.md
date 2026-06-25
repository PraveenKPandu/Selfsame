# Releasing

Releases publish to **PyPI** automatically via `.github/workflows/release.yml`
when a version tag (`vX.Y.Z`) is pushed. Publishing uses **PyPI Trusted
Publishing (OIDC)** — there is no API token stored in GitHub.

## One-time setup (PyPI Trusted Publisher)

On https://pypi.org → project **selfsame** → *Settings → Publishing → Add a
trusted publisher* (GitHub Actions), with:

| field | value |
|---|---|
| Owner | `PraveenKPandu` |
| Repository | `Selfsame` |
| Workflow name | `release.yml` |
| Environment | `pypi` |

Also create a GitHub Environment named **`pypi`** (repo → Settings →
Environments) — optionally add a required reviewer so a human approves each
publish.

(The `selfsame` project already exists on PyPI from the 0.0.1 placeholder, so the
trusted publisher is added under that existing project. The first real release is
`0.1.1`, which supersedes the stub.)

## Cutting a release

The Python package lives in `packages/python/`; the release workflow builds from there.

1. Bump `version` in `packages/python/pyproject.toml` (the workflow fails if the tag
   doesn't match it).
2. Merge to `main` via gitflow and tag:
   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```
3. The workflow builds the sdist+wheel, runs `twine check`, verifies the tag
   matches the version, and publishes to PyPI from the `pypi` environment.
4. Verify: https://pypi.org/project/selfsame/

`workflow_dispatch` (the “Run workflow” button) does a **build-only dry run** — it
builds and checks but does not publish.

## Not yet automated
npm, crates.io, Homebrew, conda-forge, Docker, and standalone binaries are out of
scope for now (PyPI-only pipeline). See the channel map in chat / future notes
when those are added.
