# Rework GitHub Actions runner

Repository: https://github.com/mattaplm/Rework

Runner name: `aplmapps01-rework`. Labels: `self-hosted`, `Linux`, `X64`,
`aplmapps01`, `rework`.

The Linux x64 runner 2.338.0 was downloaded from the official GitHub release,
verified against its SHA-256 checksum, and registered on 2026-10-28.
Automatic runner updates remain enabled. No registration token is stored here.

## Installed service

Verified on 2026-10-28: the service is active and enabled, connected to GitHub,
and reported `Listening for Jobs` at 02:01:38 UTC.

An [end-to-end smoke test](https://github.com/mattaplm/Rework/actions/runs/40618994571)
passed at 02:06:56 UTC on 2026-10-28. GitHub dispatched the job to
`aplmapps01-rework`; it verified the host and dedicated account, fetched the exact
test commit, and compiled all 35 tracked Python files successfully. This checked
runner execution and Python syntax, not application tests or a Docker build.
The temporary test branch was removed afterward. No build or deployment
workflow was added to `main` by that runner setup. Application pushes are now
handled by the app owner's polling deployment agent. The permanent
`Test and verify deployment` workflow now uses this runner to verify the exact
healthy revision over HTTP after its GitHub-hosted test job passes; see
[automatic deployment](README.md#automatic-deployment).

The runner is installed at `/opt/actions-runner-rework`, owned by the dedicated
`rework-runner` system account. Its systemd service is:

```text
actions.runner.mattaplm-Rework.aplmapps01-rework.service
```

It enables startup after reboot. The account has no sudo or Docker membership;
the service also blocks access to home directories and limits filesystem writes
to its runner directory and private temporary directory. This runner cannot
deploy the production Docker application without separately configured access.
`install-runner-service.sh` is retained as the installation record. It requires
sudo and an already-registered runner staged at
`/home/aplmadmin/actions-runner-rework`. It refuses to overwrite an existing
runner directory or account; do not rerun it on this completed installation.

## Workflow selection

Use the repository-specific labels:

```yaml
runs-on: [self-hosted, Linux, X64, aplmapps01, rework]
```

This is a public repository and the server has internal network access.
Run only trusted code on this runner. Use GitHub-hosted runners for pull request
checks, especially fork contributions; account and filesystem isolation do not
isolate access to the internal network. No permanent workflow triggers are added
by the original runner setup. The deployment verification workflow runs only
for `main`, with no pull request trigger. See GitHub's [self-hosted runner security guidance](https://docs.github.com/en/actions/concepts/runners/self-hosted-runners).

## Verification and maintenance

```sh
systemctl is-enabled actions.runner.mattaplm-Rework.aplmapps01-rework.service
systemctl status actions.runner.mattaplm-Rework.aplmapps01-rework.service
journalctl -u actions.runner.mattaplm-Rework.aplmapps01-rework.service -n 30 --no-pager
```

Confirm the log says `Listening for Jobs` and the runner appears **Idle** in
[repository runner settings](https://github.com/mattaplm/Rework/settings/actions/runners).
To stop or restart this runner, use `sudo systemctl stop` or
`sudo systemctl restart` with the exact service name above.
The Rework application and other repositories' runners use separate services.
