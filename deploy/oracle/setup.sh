#!/usr/bin/env bash
# One-time setup on the Oracle Cloud VM (Ubuntu, India region).
# Run as the default "ubuntu" user:
#   curl -fsSL https://raw.githubusercontent.com/Rushikeshay/India_Drought_Tracker/main/deploy/oracle/setup.sh | bash
set -euo pipefail

REPO_SSH="git@github.com:Rushikeshay/India_Drought_Tracker.git"
DIR="$HOME/India_Drought_Tracker"
KEY="$HOME/.ssh/idt_deploy"

echo "== 1/6 packages"
sudo apt-get update -qq
sudo apt-get install -y -qq git curl ca-certificates cron

echo "== 2/6 swap (the free 1 GB VM needs it for pandas)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "== 3/6 is WRIS reachable from here?"
if curl -s -m 30 -o /dev/null -w '%{http_code}\n' "https://indiawris.gov.in/" ; then
  echo "   reachable"
else
  echo "   NOT reachable from this VM. Stop and report this." >&2
  exit 1
fi

echo "== 4/6 deploy key"
mkdir -p ~/.ssh && chmod 700 ~/.ssh
[ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N "" -C "oracle-vm-deploy" -f "$KEY"
cat > ~/.ssh/config <<EOF
Host github.com
  IdentityFile $KEY
  IdentitiesOnly yes
EOF
ssh-keyscan -q github.com >> ~/.ssh/known_hosts 2>/dev/null
echo
echo "   Add this key at https://github.com/Rushikeshay/India_Drought_Tracker/settings/keys/new"
echo "   Title: oracle-vm   and TICK 'Allow write access'"
echo
cat "$KEY.pub"
echo
read -r -p "   Press Enter after you have added the key... " _ </dev/tty
ssh -T git@github.com 2>&1 | grep -q "successfully authenticated" || { echo "deploy key not working" >&2; exit 1; }

echo "== 5/6 clone + python env"
[ -d "$DIR/.git" ] || git clone -q "$REPO_SSH" "$DIR"
cd "$DIR"
git config user.name "Rushikeshay"
git config user.email "rushikesh.y.jadhav@gmail.com"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv venv -q --python 3.11 .venv
uv pip install -q --python .venv -r requirements.txt

echo "== 6/6 probe + cron"
(cd notebooks/phase0 && PROBE_WHERE=oracle ../../.venv/bin/python probe_wris.py) || true
chmod +x deploy/oracle/run_wris.sh
# Weekly, Sunday 03:00 IST. Groundwater readings change ~4x a year.
( crontab -l 2>/dev/null | grep -v run_wris.sh ; echo "0 3 * * 0 $DIR/deploy/oracle/run_wris.sh >> $HOME/wris.log 2>&1" ) | crontab -
sudo timedatectl set-timezone Asia/Kolkata || true
echo
echo "Done. Probe result: $DIR/notebooks/phase0/results/oracle/wris.json"
echo "First full pull (can take 1-2 h):  nohup $DIR/deploy/oracle/run_wris.sh >> ~/wris.log 2>&1 &"
