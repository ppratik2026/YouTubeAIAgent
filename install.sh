#!/bin/sh
# One-command setup on any fresh Ubuntu / Debian VPS (Hostinger, DigitalOcean, AWS, ...):
#   git clone https://github.com/ppratik2026/YouTubeAIAgent.git && cd YouTubeAIAgent && sh install.sh
# With your own cloned voice as well:  sh install.sh clone
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
if [ "$1" = "clone" ]; then
  # Voice clone service too (big download the first time: PyTorch + the Chatterbox model)
  docker compose --profile clone up -d --build
else
  docker compose up -d --build
fi
echo
echo "Running. Next:"
echo "  ./yt add --category news --lang hi --format short --count 10"
echo "  ./yt list"
echo "  ./yt logs"
