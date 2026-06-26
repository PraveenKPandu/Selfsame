# Releasing

This is a polyglot monorepo; each language package releases independently, on its
own tag prefix, via its own workflow:

| package | tag | workflow | registry |
|---|---|---|---|
| `packages/python` | `vX.Y.Z` | `release.yml` | PyPI |
| `packages/node` | `node-vX.Y.Z` | `release-node.yml` | npm |
| `packages/java` | `java-vX.Y.Z` | `release-java.yml` + `release-java-central.yml` | GitHub Release (always) + Maven Central (once secrets set) |

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

## Java → Maven Central + GitHub Release

A `java-vX.Y.Z` tag triggers two workflows:
- `release-java.yml` — always: builds the shaded `selfsame.jar` and attaches it to a
  **GitHub Release**.
- `release-java-central.yml` — **only once the Central secrets below are set**: GPG-signs and
  publishes to **Maven Central** as `io.github.praveenkpandu:selfsame`. Until configured it
  no-ops (so it never blocks the GitHub Release).

Coordinate (Maven): `io.github.praveenkpandu:selfsame:X.Y.Z`. The Maven groupId is
`io.github.praveenkpandu` (GitHub-verified namespace — no domain needed); the Java package
stays `dev.selfsame` (the two are independent).

### One-time setup (maintainer; I can't do these — accounts/keys)
1. **Central Portal account + namespace.** Sign in at https://central.sonatype.com with GitHub.
   Register the namespace **`io.github.praveenkpandu`** → it offers GitHub verification (creates
   a temporary verification repo / checks account ownership). Once verified, you can publish
   under `io.github.praveenkpandu:*`.
2. **Portal token.** Central Portal → *Account → Generate User Token* → gives a username +
   password pair. Add as repo secrets `CENTRAL_TOKEN_USERNAME` / `CENTRAL_TOKEN_PASSWORD`.
3. **GPG signing key.** Generate one and publish the public key:
   ```bash
   gpg --quick-generate-key "PraveenKPandu <praveenkpandu@gmail.com>" rsa4096
   gpg --keyserver keyserver.ubuntu.com --send-keys <KEY_ID>      # also keys.openpgp.org
   gpg --armor --export-secret-keys <KEY_ID>                       # paste into the secret below
   ```
   Add repo secrets `GPG_PRIVATE_KEY` (the ASCII-armored private key) and `GPG_PASSPHRASE`.

### Cutting a release
1. Bump `<version>` in `packages/java/pom.xml`.
2. `git tag java-vX.Y.Z && git push origin java-vX.Y.Z`.
3. `release-java-central.yml` runs `mvn -P release deploy` — builds the jar + `-sources` +
   `-javadoc`, GPG-signs them, and publishes via the Central Portal (`autoPublish`). Verify:
   https://central.sonatype.com (and, after sync, https://repo1.maven.org/maven2/io/github/praveenkpandu/selfsame/).

You can validate the build locally without publishing:
`cd packages/java && mvn -P release -DskipTests -Dgpg.skip=true package` (produces the jar +
sources + javadoc).

---

## Not yet automated
crates.io (Rust — held), Homebrew, conda-forge, Docker, and standalone binaries
are out of scope for now.
