# Claiming the name "selfsame"

Availability re-verified directly against each registry (HTTP 404 = available):

| Surface | Status | How to claim |
|---|---|---|
| PyPI `selfsame` | available | publish the stub in `pypi/` |
| npm `selfsame` | available | publish the stub in `npm/` |
| crates.io `selfsame` | available | publish the stub in `crates/` |
| GitHub `github.com/selfsame` | **TAKEN** (user "Joseph Parker", since 2012) | not obtainable — see below |

**Important:** publishing to a public registry is effectively irreversible — once
a name is taken you can't free it or hand it to a different account, and yanking
a version does **not** release the name. Each publish happens under *your*
account and needs *your* API token. These 0.0.1 stubs just reserve the name; you
can push the real project later as a higher version (you'll own the name).

## PyPI
1. Account at https://pypi.org + an API token (Account settings → API tokens).
2. ```bash
   cd name-claim/pypi
   python3 -m pip install --upgrade build twine
   python3 -m build
   python3 -m twine upload dist/*        # username: __token__   password: <pypi token>
   ```
3. Verify: https://pypi.org/project/selfsame/

## npm
1. Account at https://www.npmjs.com, then `npm login`.
2. ```bash
   cd name-claim/npm
   npm publish --access public
   ```
3. Verify: https://www.npmjs.com/package/selfsame

## crates.io
1. Log in at https://crates.io with GitHub, create an API token, then
   `cargo login <token>`.
2. ```bash
   cd name-claim/crates
   cargo publish        # add --allow-dirty if running from the repo tree
   ```
3. Verify: https://crates.io/crates/selfsame

## GitHub — name is taken
`github.com/selfsame` is an existing, active user account, so the vanity
namespace can't be claimed. Options:
- Keep the repo at `PraveenKPandu/Selfsame` (already done).
- Create a GitHub **organization** under an available handle (e.g. `selfsame-dev`,
  `selfsame-io`, `getselfsame`) and move/mirror the repo there. (Org creation is a
  manual step in the GitHub UI; check the handle first at github.com/<name>.)

## Domains (optional, registrar + payment required — not automatable here)
Check & register via a registrar (Namecheap/Cloudflare/etc.):
- selfsame.dev, selfsame.io, selfsame.sh, selfsame.tools, getselfsame.com
`.dev`/`.io` are common for dev tools; `.com` is likely taken (verify).

## Also worth reserving (same publish-to-claim model)
- Test PyPI (https://test.pypi.org) — optional dry run before the real PyPI push.
- Read the Docs project slug `selfsame` (if you'll host docs).
- A social/handle if relevant (e.g. GitHub org as above).
