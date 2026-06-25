# Releasing

This is a polyglot monorepo; each language package releases independently, on its
own tag prefix, via its own workflow:

| package | tag | workflow | registry |
|---|---|---|---|
| `packages/python` | `vX.Y.Z` | `release.yml` | PyPI |
| `packages/node` | `node-vX.Y.Z` | `release-node.yml` | npm |
| `packages/java` | `java-vX.Y.Z` | `release-java.yml` | GitHub Release (Maven Central is a future step) |

All three are tokenless where possible (OIDC). Each workflow's `workflow_dispatch`
button is a build-only dry run.

---

## Python → PyPI

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

---

## JavaScript → npm

`release-node.yml` publishes `packages/node` to **npm** on a `node-vX.Y.Z` tag,
using **npm Trusted Publishing (OIDC)** with provenance — no NPM token in GitHub.

### One-time setup
1. **First publish bootstraps the name.** npm trusted publishing can only be
   configured on a package that already exists, so the very first publish is
   manual: `cd packages/node && npm publish --access public` (the maintainer runs
   this locally after `npm login` — never paste the token here).
2. On npmjs.com → package **selfsame** → *Settings → Trusted Publisher* → add the
   GitHub Actions publisher: repo `PraveenKPandu/Selfsame`, workflow
   `release-node.yml`. Subsequent releases are then tokenless.

### Cutting a release
1. Bump `version` in `packages/node/package.json`.
2. `git tag node-vX.Y.Z && git push origin node-vX.Y.Z`.
3. The workflow verifies tag == version, runs the tests, and `npm publish
   --provenance`. Verify: https://www.npmjs.com/package/selfsame

## Java → GitHub Release (Maven Central later)

`release-java.yml` builds the jar with plain `javac`/`jar` (the core is pure JDK,
no dependencies) and attaches it to a **GitHub Release** on a `java-vX.Y.Z` tag.

1. Bump `<version>` in `packages/java/pom.xml`.
2. `git tag java-vX.Y.Z && git push origin java-vX.Y.Z`.
3. The workflow runs the tests, builds `selfsame-X.Y.Z.jar`, and creates the
   Release with the jar attached.

**Maven Central** is deliberately deferred: it requires owning the `dev.selfsame`
namespace (Sonatype Central Portal verification) and a published GPG signing key —
maintainer-side external setup. Once that exists, swap the build step for
`mvn -B deploy` with the Central publishing plugin + signing.

---

## Not yet automated
crates.io (Rust — held), Homebrew, conda-forge, Docker, and standalone binaries
are out of scope for now.
