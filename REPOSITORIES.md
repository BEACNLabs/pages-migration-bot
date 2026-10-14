# BEACNLabs Pages publishing routes

Verified in GitHub Settings → Pages on 2026-10-14 after the account rename.

| Repository | Source | Public URL |
|---|---|---|
| ABCDE | `gh-pages`, root; editable site also in `main/web/dist` | https://beacnlabs.github.io/ABCDE/ |
| beacn-drep-web | `main`, root | https://beacnlabs.github.io/beacn-drep-web/ |
| cardano-devtools-directory | `main`, root | https://beacnlabs.github.io/cardano-devtools-directory/ |
| ledger-scrolls | `main`, root | https://beacnlabs.github.io/ledger-scrolls/ |
| NFT-Studio | `gh-pages`, root; built from `main` | https://beacnlabs.github.io/NFT-Studio/ |
| town-ledger | GitHub Actions, `.github/workflows/pages.yml` | https://beacnlabs.github.io/town-ledger/ |

All six use HTTPS without a custom domain. The unused `gh-pages` branch in
beacn-drep-web is not its publishing source. Recheck settings before future repairs.

## Preserve these boundaries

- ABCDE's archived pool records, original artwork and data snapshots retain their
  original contents. Regenerate its archive navigation from its maintained source.
- DRep rationale files and manifests are evidence, not branding text.
- Ledger Scrolls' on-chain mirrors and schema identifiers stay byte-identical.
  Run its navigation generator and frozen-file checks when updating site links.
- NFT-Studio's original media, recorded receipts, intents, protocol identities and
  transaction baselines stay unchanged. A review URL's hostname may migrate while
  its complete fragment remains identical. Follow `docs/PUBLISHING.md`; rebuild
  hashed assets and preserve older chunks for open tabs.
- Town Ledger remains separate from the frozen Cryer review site.

The migration audit covers the important routes in `routes.json`. Frozen records
and historical recordings may still contain old URLs. An old URL inside such an
artifact is not permission to rewrite its evidence. Retired APIs are separate from
Pages availability and are not reactivated by this bot.

Google Safe Browsing can classify the shared `beacnlabs.github.io` hostname
separately from GitHub's deployment status. Neither a successful audit nor a new
repository name establishes that a browser warning was cleared.
