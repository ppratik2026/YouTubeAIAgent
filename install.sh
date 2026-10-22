#!/bin/sh
# One-command setup on any fresh Ubuntu / Debian VPS (Hostinger, DigitalOcean, AWS, ...):
#   git clone https://github.com/ppratik2026/YouTubeAIAgent.git && cd YouTubeAIAgent && sh install.sh
# Options (any order):  clone = your own cloned voice   https = dashboard on https://$DOMAIN
set -e
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi

mkdir -p data assets/music
if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo "Created .env - open it (nano .env), fill in your keys, then run: sh install.sh"
  exit 0
fi

chmod +x yt
mkdir -p data/voices data/inbox
profiles=""
for opt in "$@"; do
  case "$opt" in
    clone) profiles="$profiles --profile clone" ;;  # big first download: PyTorch + the Chatterbox model
    https)
      grep -q '^DOMAIN=..*' .env || { echo "Set DOMAIN=your.domain in .env first (it must point at this server)"; exit 1; }
      profiles="$profiles --profile https" ;;
  esac
done
grep -q '^DASHBOARD_PASSWORD=.\{8,\}' .env || echo "Note: set DASHBOARD_PASSWORD (8+ characters) in .env to use the dashboard."
# shellcheck disable=SC2086
docker compose $profiles up -d --build
echo
echo "Running. Next:"
echo "  ./yt add --category news --lang hi --format short --count 10"
echo "  ./yt list"
echo "  ./yt logs"
echo "Dashboard: https://\$DOMAIN (with https), or from your PC: ssh -L 8080:localhost:8080 root@SERVER -> http://localhost:8080"
