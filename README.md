# Pages Migration Bot

Find and repair GitHub Pages links after a GitHub account rename. Python 3.10+ and Git are the only local requirements. No paid service or new credential is needed for public-site audits.

The bot inventories all public repositories for an owner, finds the ones with Pages enabled, checks their current URLs and local assets, and reports links that still point to the old account. It keeps HTTP availability separate from browser security warnings: **HTTP 200 does not mean Chrome considers a site safe.**

## Run an audit

On GitHub, open [Actions → Audit Pages after account rename](https://github.com/BEACNLabs/pages-migration-bot/actions/workflows/audit.yml)
and choose **Run workflow**. The run summary and downloadable artifact contain
the results. [Publishing routes](REPOSITORIES.md) document the six maintained sites.

```sh
python3 pages_bot.py audit \
  --owner BEACNLabs --previous-owner BEACNpool \
  --routes routes.json --output reports/audit.json
```

JSON and Markdown reports identify HTTP failures, stale links, failed assets and outdated repository homepage URLs. `routes.json` adds important subpages to the root-page checks. The included GitHub Actions workflow runs this audit on demand and after bot changes, retaining its reports as artifacts. Add `--fail-on-issues` for a nonzero exit when a check finds problems.

The public inventory does not enumerate private repositories. If private Pages sites exist, inspect them through an authorized account separately; never publish private repository metadata in an audit artifact. An optional `GH_TOKEN` or `GITHUB_TOKEN` raises the GitHub API rate limit. Credentials are sent only to `api.github.com`, never to the audited sites or reports.

## Repair reviewed files

Use an isolated, clean checkout of the actual publishing branch. Confirm **Settings → Pages** first: a repository's default branch may differ from its Pages branch.

```sh
python3 pages_bot.py plan \
  --repo /path/to/isolated-checkout \
  --owner BEACNLabs --previous-owner BEACNpool \
  --files index.html app.js README.md \
  --output reports/repo-plan.json

python3 pages_bot.py apply \
  --repo /path/to/isolated-checkout \
  --plan reports/repo-plan.json \
  --backup /path/outside-checkout/before-repair
```

`plan` changes nothing in the checkout. `apply` verifies the commit and file hashes, creates and reads back a backup, and applies only the exact URL replacements in the plan. It refuses dirty checkouts, stale plans, symlinks, path traversal and modified plan hashes. Run the repository's existing checks, inspect the diff, commit the specific files and make a normal push. Then rerun the live audit.

Only exact old GitHub Pages hosts and GitHub/raw/API owner URL segments change. Brand names, other domains, schema identities, signed records, frozen artwork and historical data must not be selected for repair. Generated pages should be regenerated from their maintained sources and compared with the intended URL-only change. Repository homepages and Pages settings use GitHub's authenticated administration interface; this tool reports them rather than silently changing account settings.

## What this cannot repair

- Google Safe Browsing classifications. Inspect the site, use Google's official review process, and verify the browser independently. Republishing does not establish that a warning was cleared.
- Retired backends or external services, such as an intentionally closed API.
- Old bookmarks under the former `github.io` hostname. Publish and share the new address.
- Browser-local drafts stored under the old origin. A repository rename does not migrate browser storage.
- All dynamic routes or application behavior. The audit parses HTML and checks up to 64 first-level local assets per route; it reports truncation and untested assets.

The bot does not delete repositories, force-push, bypass browser warnings, sign transactions, or activate retired jobs. Repairs are explicit and reviewable; its GitHub workflow is read-only.

## Test

```sh
python3 -m unittest -v test_pages_bot
```

Tests cover URL boundaries, preserved paths and fragments, pagination, security-status separation, verified backups, dirty work, stale plans, tampering and unsafe paths.

## References

- [GitHub: changing a username](https://docs.github.com/en/account-and-profile/concepts/changing-your-github-username)
- [GitHub: configuring a Pages publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
- [GitHub: unpublishing and restoring Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/unpublishing-a-github-pages-site)
- [Google: Security Issues report and review process](https://support.google.com/webmasters/answer/9044101)

MIT licensed. No browser-safety guarantee is implied by the audit.
