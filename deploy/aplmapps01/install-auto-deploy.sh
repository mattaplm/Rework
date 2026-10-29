#!/usr/bin/env bash
# Run as aplmadmin on APLMAPPS01. No sudo or runner permission changes needed.
set -euo pipefail

root=/home/aplmadmin/rework
if [[ $(hostname -s) != aplmapps01 || $(id -un) != aplmadmin ]]; then
    echo 'Run as aplmadmin on APLMAPPS01.' >&2
    exit 1
fi
test -f "$root/.env"
test -f "$root/compose.yml"
test -f "$root/data/rework.sqlite3"
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
install -m 700 "$source_dir/auto_deploy.py" "$root/auto_deploy.py.new"
mv -- "$root/auto_deploy.py.new" "$root/auto_deploy.py"
install -d -m 700 "$root/.autodeploy"

schedule=$(mktemp)
trap 'rm -f -- "$schedule"' EXIT
# This host already has scheduled jobs for other apps and Rework's backup.
# Read successfully before editing; never replace the crontab after a read error.
crontab -l > "$schedule"
python3 - "$schedule" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = [line for line in path.read_text().splitlines()
         if not line.endswith(" # rework-auto-deploy")]
lines.append("* * * * * /usr/bin/python3 /home/aplmadmin/rework/auto_deploy.py "
             ">> /home/aplmadmin/rework/.autodeploy/cron.log 2>&1 # rework-auto-deploy")
path.write_text("\n".join(lines) + "\n")
PY
crontab "$schedule"
echo 'Automatic deployment enabled for pushes to mattaplm/Rework main.'
