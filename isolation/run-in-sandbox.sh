#!/usr/bin/env bash
# Advisory command isolation. The host agent and MCP are outside this container.
set -euo pipefail

usage() {
  echo 'Usage: run-in-sandbox.sh --checkout DIR --image TRUSTED_LOCAL_IMAGE -- COMMAND [ARG ...]' >&2
  exit 2
}

checkout=''
image=''
while (($#)); do
  case "$1" in
    --checkout) (($# >= 2)) && [[ -z "$checkout" ]] || usage; checkout="$2"; shift 2 ;;
    --image) (($# >= 2)) && [[ -z "$image" ]] || usage; image="$2"; shift 2 ;;
    --) shift; break ;;
    *) usage ;;
  esac
done
[[ -n "$checkout" && -n "$image" && $# -gt 0 && -n "$1" && "$1" != -* ]] || usage

# Resolve before mounting, including symlinks; never interpolate repository data
# into shell code. Commas would be interpreted by Docker's --mount CSV parser.
checkout=$(python3 -I -S - "$checkout" "$image" "$@" <<'PY'
from pathlib import Path
import re
import sys
import unicodedata

def refuse(reason):
    print("Refused sandbox arguments: " + reason, file=sys.stderr)
    sys.exit(2)

def has_controls(value):
    return any(unicodedata.category(c) in ('Cc', 'Cf') for c in value)

if any(has_controls(arg) for arg in sys.argv[1:]):
    refuse("control characters are not allowed")
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@-]*", sys.argv[2]):
    refuse("select an explicit trusted image name or digest")
try:
    path = Path(sys.argv[1]).resolve(strict=True)
except (OSError, RuntimeError):
    refuse("checkout must be an existing directory")
if not path.is_dir() or ',' in str(path) or has_controls(str(path)):
    refuse("checkout must be a directory with an unambiguous mount path")
home = Path.home().resolve()
if path == Path('/') or path == home or path in home.parents or path.parent in (Path('/Users'), Path('/home')):
    refuse("root, home and their parent directories are not checkouts")
system = ('/etc', '/bin', '/sbin', '/usr', '/lib', '/lib64', '/var', '/private/etc',
          '/private/var', '/System', '/Library', '/Applications', '/opt', '/proc',
          '/sys', '/dev', '/run', '/boot', '/root')
if str(path) in ('/tmp', '/private', '/private/tmp', '/Users', '/home', '/Volumes'):
    refuse("a shared directory is not a dedicated checkout")
for name in system:
    base = Path(name).resolve()
    if path == base or base in path.parents:
        refuse("system directories are not checkouts")
for name in ('.ssh', '.aws', '.config', '.claude', '.codex', '.docker', '.kube', 'Library'):
    base = (home / name).resolve()
    if path == base or base in path.parents:
        refuse("host configuration directories are not checkouts")
if any(part in ('.ssh', '.aws', '.config', '.claude', '.codex', '.docker', '.kube') for part in path.parts):
    refuse("configuration directories are not dedicated checkouts")
print(path)
PY
)

command=("$@")
docker_args=(run --rm --pull=never --network=none --cap-drop=ALL
  --security-opt=no-new-privileges --read-only --pids-limit=128
  --user "$(id -u):$(id -g)" --tmpfs /tmp:rw,nosuid,nodev,size=256m
  --env HOME=/tmp --env TMPDIR=/tmp
  --mount "type=bind,src=$checkout,dst=/work" --workdir /work
  --entrypoint "${command[0]}" "$image" "${command[@]:1}")
exec docker "${docker_args[@]}"
