# btc_dashboard (vendored)

Snapshot of `src/` from [WeTheAgents/btc_dashboard](https://github.com/WeTheAgents/btc_dashboard),
vendored here because that repo is private and a cross-repo `actions/checkout`
with `GITHUB_TOKEN` fails.

Used by:
- `scripts/btc_snapshot_build.js` — daily static snapshot builder
- `.github/workflows/btc-snapshot.yml` — cron runner

## Updating

To pull upstream changes:

```bash
cp -r D:/GitHub/btc_dashboard/src     D:/GitHub/wetheagents/vendor/btc_dashboard/src
cp    D:/GitHub/btc_dashboard/package.json       D:/GitHub/wetheagents/vendor/btc_dashboard/
cp    D:/GitHub/btc_dashboard/package-lock.json  D:/GitHub/wetheagents/vendor/btc_dashboard/
```

Then run the builder locally (`node scripts/btc_snapshot_build.js`) to
confirm the string replacements in `docs/btc/app.js` still apply — if
`btc_dashboard/src/public/app.js` drifted, the builder will fail loudly
with an `assertReplace` error naming the broken patch.

## Not committed

- `node_modules/` — installed by CI via `npm ci`
- `data/` — runtime cache, not needed for the snapshot builder
