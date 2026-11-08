#!/usr/bin/env bash
# Install or update DQ Workbench as a daily systemd job on a Linux host/container.
#
# Usage (as root):  ./install.sh [git-ref]      (default: main)
# Re-run with a new ref to update. The config at /etc/dq-workbench/config.yml is never overwritten.
set -euo pipefail

REF="${1:-main}"
REPO_URL="${DQ_WORKBENCH_REPO:-https://github.com/dhis2-utils/tool-dq-workbench.git}"
APP_DIR=/opt/dq-workbench
CONF_DIR=/etc/dq-workbench
LOG_DIR=/var/log/dq-workbench
APP_USER=dqworkbench

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root" >&2
  exit 1
fi

echo "== Packages"
apt-get update -qq
apt-get install -y -qq git python3 python3-venv ca-certificates >/dev/null

echo "== Service user"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"

echo "== Code at $REF"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone --quiet "$REPO_URL" "$APP_DIR"
fi
git -C "$APP_DIR" fetch --quiet --tags origin
git -C "$APP_DIR" checkout --quiet --force "$REF"
# If REF is a branch, move to its latest commit
if git -C "$APP_DIR" show-ref --verify --quiet "refs/remotes/origin/$REF"; then
  git -C "$APP_DIR" reset --quiet --hard "origin/$REF"
fi
echo "   $(git -C "$APP_DIR" log -1 --format='%h %s')"

echo "== Python environment"
[ -d "$APP_DIR/.venv" ] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet "$APP_DIR"
chown -R root:root "$APP_DIR"

echo "== Config and log directories"
install -d -o root -g "$APP_USER" -m 750 "$CONF_DIR"
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$LOG_DIR"
if [ -f "$CONF_DIR/config.yml" ]; then
  chown root:"$APP_USER" "$CONF_DIR/config.yml"
  chmod 640 "$CONF_DIR/config.yml"
else
  echo "   NOTE: $CONF_DIR/config.yml does not exist yet; copy it in before the first run"
fi

echo "== systemd units"
install -m 644 "$APP_DIR/deploy/dq-workbench.service" /etc/systemd/system/dq-workbench.service
install -m 644 "$APP_DIR/deploy/dq-workbench.timer" /etc/systemd/system/dq-workbench.timer
systemctl daemon-reload
systemctl enable --now dq-workbench.timer
systemctl list-timers dq-workbench.timer --no-pager

echo "Done. Run once now with: systemctl start dq-workbench.service && journalctl -u dq-workbench -f"
