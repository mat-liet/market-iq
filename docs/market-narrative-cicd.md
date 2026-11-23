# CI/CD pipeline

Everything runs in GitHub Actions, in `.github/workflows/ci.yml`. Pull requests are
tested. Pushes to `main` are tested and then deployed to the production server over
SSH.

```
pull request ──► backend tests ─┐
                 frontend tests ┴─► (stop)

push to main ──► backend tests ─┐
                 frontend tests ┴─► deploy ──ssh──► deploy/deploy.sh <commit>
                                                      │ git reset to <commit>
                                                      │ docker compose up -d --build
                                                      │ wait for app healthcheck
                                                      └ healthy? done : roll back, fail
```

## Jobs

- **backend**: Python 3.11 against a throwaway PostgreSQL 15 service container.
  `pytest` runs with `APP_ENV=test`, so there are no live Claude calls and the
  committed example feeds and taxonomy are used.
- **frontend**: `npm ci`, lint, tests and production build.
- **deploy**: runs only on `push` to `main`, after both test jobs pass, and only
  when the `DEPLOY_HOST` repository variable is set. It is serialized by a
  `production-deploy` concurrency group, so deploys never overlap and none is
  cancelled mid-way. It is recorded under the `production` environment.

## Secrets and trust

| Name | Kind | Purpose |
|---|---|---|
| `DEPLOY_SSH_KEY` | secret | Private key whose server entry is forced to `deploy/deploy.sh` (`restrict`: no shell, no forwarding) |
| `DEPLOY_HOST` | variable | Server address; also the switch that enables the deploy job |
| `DEPLOY_KNOWN_HOSTS` | variable | The server's SSH host key, so the job never trusts a scanned key |

The Claude API key, database password and dashboard credentials live only in `.env`
on the server. The private feed list and taxonomy live only in `config/` on the
server. None of them pass through CI.

What the CI key can do on the server: deploy a commit that is on `origin/main` and
is the running commit or newer. Nothing else.

No third-party Actions are used in the deploy job. It is plain `ssh` on the runner.

## Rollbacks

- **Automatic:** a release whose app doesn't pass its healthcheck within two minutes
  is replaced by the previous commit, and the job fails.
- **By hand:** on the server, run `./deploy/deploy.sh <older-sha>`. This is
  deliberately not possible through CI.
- **Schema:** migrations are forward-only on container start, so a code rollback
  doesn't undo them. Restore from the nightly backup if a migration has to be
  reverted.

Setup steps are in [`deployment.md`](deployment.md#6-automatic-deploys).
