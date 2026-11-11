#!/usr/bin/env bash
# Installs ffmpeg and fails fast if the runner's apt mirror hangs.
set -euo pipefail

apt_opts=(-o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 -o Acquire::Retries=3)

install_ffmpeg() {
  # Hard cap per attempt so the fallback still fits in the step's timeout-minutes.
  sudo timeout 180 apt-get "${apt_opts[@]}" update &&
    sudo timeout 180 apt-get "${apt_opts[@]}" install -y --no-install-recommends ffmpeg
}

if install_ffmpeg; then
  exit 0
fi

echo "::warning::ffmpeg install failed, retrying with archive.ubuntu.com"
# ubuntu-24.04 runners use deb822 files; the legacy sources.list may not exist.
files=(/etc/apt/sources.list.d/*.sources)
[ -f /etc/apt/sources.list ] && files+=(/etc/apt/sources.list)
sudo sed -i -E 's#https?://[a-z0-9.-]*archive\.ubuntu\.com/ubuntu/?#http://archive.ubuntu.com/ubuntu/#' "${files[@]}"
install_ffmpeg
