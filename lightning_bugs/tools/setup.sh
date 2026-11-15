#!/usr/bin/env bash
# Installs everything lb_flash.py needs, without root and without distro packages:
#   - arduino-cli (pinned, checksum-verified release tarball) -> ~/.local/bin
#   - the py32duino core (+ its toolchain and CMSIS) via arduino-cli
#   - a Python venv (lightning_bugs/.venv) with pyocd and the Puya pack
# Safe to re-run. See assessments/toolchain.md for why.
#
# Hazardous outside a sandbox (installs into ~/.local/bin and downloads and runs
# tools), so it refuses to run anywhere but inside a claude_sandbox container,
# where claude_sandbox_deps.yaml runs it at every launch. Do not remove the guard.

# Refuse to run anywhere but inside a claude_sandbox container.
[ -f /etc/claude-sandbox ] || { echo "refusing: not inside a claude_sandbox container" >&2; exit 1; }

set -euo pipefail

ARDUINO_CLI_VERSION=0.33.0   # the version py32duino's own CI uses
CORE=PY32Duino:PY32@0.1.3
INDEX_URL=https://github.com/PY32Duino/Arduino-pack-json-ci/releases/download/Nightly/package_py32_index.json
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

arch="$(uname -m)"
case "$arch" in
  x86_64)  asset=Linux_64bit ;;
  aarch64) asset=Linux_ARM64 ;;
  *) echo "unsupported architecture: $arch" >&2; exit 1 ;;
esac

# claude_sandbox_deps.yaml installs a pinned arduino-cli to /usr/local/bin; reuse
# whatever is on PATH if it is the pinned version, otherwise install our own.
mkdir -p "$BIN_DIR"
export PATH="$BIN_DIR:$PATH"
if [ "$(arduino-cli version 2>/dev/null | awk '{print $3}')" != "$ARDUINO_CLI_VERSION" ]; then
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  base="https://github.com/arduino/arduino-cli/releases/download/${ARDUINO_CLI_VERSION}"
  tarball="arduino-cli_${ARDUINO_CLI_VERSION}_${asset}.tar.gz"
  echo "Downloading $tarball"
  curl -fsSL -o "$tmp/$tarball" "$base/$tarball"
  curl -fsSL -o "$tmp/checksums.txt" "$base/${ARDUINO_CLI_VERSION}-checksums.txt"
  (cd "$tmp" && grep " $tarball\$" checksums.txt | sha256sum -c -)
  tar -xzf "$tmp/$tarball" -C "$tmp" arduino-cli
  install -m 0755 "$tmp/arduino-cli" "$BIN_DIR/arduino-cli"
fi
export PATH="$BIN_DIR:$PATH"
arduino-cli version

arduino-cli config init --overwrite >/dev/null 2>&1 || true
arduino-cli core update-index --additional-urls "$INDEX_URL"
arduino-cli core install "$CORE" --additional-urls "$INDEX_URL"

if [ ! -x "$ROOT/.venv/bin/pyocd" ]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q --upgrade pip pyocd
fi
"$ROOT/.venv/bin/pyocd" pack update >/dev/null 2>&1 || true
"$ROOT/.venv/bin/pyocd" pack install py32f030x8 || echo "note: pack install failed; run '.venv/bin/pyocd pack find py32f030' and install the match" >&2

cat <<EOF

Done. Add to your shell:   export PATH="$BIN_DIR:$ROOT/.venv/bin:\$PATH"
Then:                      python3 tools/lb_flash.py build
EOF
