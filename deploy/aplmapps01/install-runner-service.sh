#!/usr/bin/env bash
# Finish the already-registered Rework runner installation on APLMAPPS01.
set -euo pipefail

source_dir=/home/aplmadmin/actions-runner-rework
runner_dir=/opt/actions-runner-rework
runner_user=rework-runner
service=actions.runner.mattaplm-Rework.aplmapps01-rework.service

if [[ $EUID -ne 0 || $(hostname -s) != aplmapps01 ]]; then
    echo 'Run with sudo on APLMAPPS01.' >&2
    exit 1
fi
if [[ -e $runner_dir || -L $runner_dir ]] || getent passwd "$runner_user" >/dev/null; then
    echo 'Runner directory or account already exists; inspect before retrying.' >&2
    exit 1
fi
if [[ ! -d $source_dir || -L $source_dir || -e /etc/systemd/system/$service ]]; then
    echo 'Staged runner is missing, is a symlink, or its service already exists.' >&2
    exit 1
fi
python3 - "$source_dir/.runner" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8-sig") as stream:
    runner = json.load(stream)
if (runner.get("agentName") != "aplmapps01-rework"
        or runner.get("gitHubUrl", "").rstrip("/").lower()
        != "https://github.com/mattaplm/rework"):
    raise SystemExit("Staged runner does not belong to mattaplm/Rework.")
PY

useradd --system --user-group --home-dir "$runner_dir" --no-create-home \
    --shell /usr/sbin/nologin "$runner_user"
mv -- "$source_dir" "$runner_dir"
chown -R "$runner_user:$runner_user" "$runner_dir"
chmod 700 "$runner_dir"
cd "$runner_dir"
# Avoid inheriting paths into the administrator's private home directory.
printf '%s\n' /usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin > .path
./svc.sh install "$runner_user"

install -d -m 755 "/etc/systemd/system/$service.d"
cat > "/etc/systemd/system/$service.d/isolation.conf" <<'UNIT'
[Service]
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/opt/actions-runner-rework
UMask=0077
UNIT
systemctl daemon-reload
systemctl start "$service"
systemctl is-enabled "$service"
systemctl --no-pager --full status "$service"
