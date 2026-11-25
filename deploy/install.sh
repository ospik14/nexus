#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf '%s\n' 'Usage: ./deploy/install.sh [--docker] [--build]'
  printf '%s\n' 'Run as a regular administrator from a trusted checkout. It invokes sudo for installation.'
  printf '%s\n' 'Pass --build to compile the frontend here, or provide frontend/dist from a build machine.'
}

docker=false
build=false
for argument in "$@"; do
  case "$argument" in
    --docker) docker=true ;;
    --build) build=true ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

if (( EUID == 0 )); then
  printf '%s\n' 'Run the installer without sudo. Dependency installation is unprivileged.' >&2
  exit 1
fi

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$source_dir"
/usr/bin/python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ is required"'
if $build; then
  (cd frontend && npm ci --no-fund && npm run build)
fi
if [[ ! -f frontend/dist/index.html ]]; then
  printf '%s\n' 'Supply frontend/dist or use --build with Node.js installed.' >&2
  exit 1
fi

if $docker && ! getent group docker >/dev/null; then
  printf '%s\n' 'The optional collector requires a local Docker Engine with a docker group.' >&2
  exit 1
fi

stage="$(mktemp -d)"
trap 'rm -rf -- "$stage"' EXIT
package="$stage/release"
mkdir -p "$package/frontend"
cp -R -- nexus migrations alembic.ini "$package/"
find "$package" -type d -name __pycache__ -prune -exec rm -rf -- {} +
cp -R -- frontend/dist "$package/frontend/"
/usr/bin/python3 -m venv "$package/.venv"
requirements=deploy/requirements.txt
if $docker; then requirements=deploy/requirements-docker.txt; fi
"$package/.venv/bin/python" -m pip install --require-hashes --only-binary=:all: -r "$requirements"
"$package/.venv/bin/python" -m pip check

sudo -v
if ! id nexus >/dev/null 2>&1; then
  sudo useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin nexus
fi
sudo install -d -m 0755 -o root -g root /opt/nexus /opt/nexus/releases
sudo install -d -m 0750 -o root -g nexus /etc/nexus
sudo install -d -m 0700 -o nexus -g nexus /var/lib/nexus
if ! sudo test -e /etc/nexus/nexus.env; then
  sed -e 's|^NEXUS_STATE_DIR=.*|NEXUS_STATE_DIR=/var/lib/nexus|' \
      -e 's|^NEXUS_WORKSPACE_CONFIG=.*|NEXUS_WORKSPACE_CONFIG=/etc/nexus/workspaces.toml|' .env.example > "$stage/nexus.env"
  sudo install -m 0640 -o root -g nexus "$stage/nexus.env" /etc/nexus/nexus.env
fi
if ! sudo test -e /etc/nexus/workspaces.toml; then
  sudo install -m 0640 -o root -g nexus config/workspaces.example.toml /etc/nexus/workspaces.toml
fi
ln -s /etc/nexus/nexus.env "$package/.env"

release="/opt/nexus/releases/$(date -u +%Y%m%dT%H%M%SZ)-${stage##*.}"
sudo cp -R --preserve=mode,timestamps -- "$package" "$release"
sudo chown -hR root:root "$release"
sudo chmod -R a+rX,go-w "$release"

sudo install -m 0644 deploy/nexus.service /etc/systemd/system/nexus.service
if $docker; then
  if ! id nexus-docker >/dev/null 2>&1; then
    sudo useradd --system --gid nexus --home-dir /nonexistent --shell /usr/sbin/nologin nexus-docker
  fi
  if ! id nexus-docker-gate >/dev/null 2>&1; then
    sudo useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin nexus-docker-gate
  fi
  if ! sudo test -e /etc/nexus/docker.env; then
    sudo install -m 0600 -o root -g root deploy/docker.env.example /etc/nexus/docker.env
  fi
  sudo install -m 0644 deploy/nexus-docker.service deploy/nexus-docker-gate.service deploy/nexus-docker-gate.socket /etc/systemd/system/
fi
sudo ln -s -- "$release" "/opt/nexus/.current-${stage##*.}"
sudo mv -Tf -- "/opt/nexus/.current-${stage##*.}" /opt/nexus/current
sudo systemctl daemon-reload
printf 'Nexus installed at %s\n' "$release"
printf '%s\n' 'Set the production origin, initialize the administrator account, and start Nexus using README.md.'
