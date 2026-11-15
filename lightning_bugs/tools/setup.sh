#!/usr/bin/env bash
# Installs everything lb_flash.py needs, without root and without distro packages:
#   - arduino-cli (pinned, checksum-verified release tarball)
#   - the py32duino core (+ its toolchain and CMSIS) via arduino-cli
#   - a Python venv (lightning_bugs/.venv) with pyocd and pyftdi (versions pinned in constraints.txt)
#     and the FT232R probe plugin
# Safe to re-run. See assessments/toolchain.md for why.
#
# Two modes. Both are hazardous outside a sandbox (they download and run tools and write files), so the
# script refuses to run anywhere but inside a claude_sandbox container unless you opt in. Do not remove
# the guard; the opt-in is the narrower, explicit way to run it elsewhere:
#
#   In a claude_sandbox container (claude_sandbox_deps.yaml runs it at every launch, no arguments):
#       arduino-cli -> ~/.local/bin, core and toolchain -> ~/.arduino15, venv -> lightning_bugs/.venv
#
#   On your own machine, only with --i-know-this-modifies-my-system:
#       everything is kept under lightning_bugs/.tools/ (git-ignored) and lightning_bugs/.venv:
#         .tools/bin            the pinned arduino-cli (your own arduino-cli is never replaced)
#         .tools/arduino15      core, toolchain, index (your ~/.arduino15 and its config are not touched)
#         .tools/arduino-user   arduino-cli's sketchbook dir (so ~/Arduino is not created)
#         .tools/arduino-downloads   its download staging dir (it defaults to ~/.arduino15/staging, ~300 MB)
#       Still written outside the repo, additively: pip's download cache and pyocd's CMSIS-Pack cache
#       (the Puya pack, in your user data dir). Linux only. Needs curl, tar, sha256sum, python3 with venv.
#       The script prints the exports to use afterwards; lb_flash.py honours ARDUINO_DIRECTORIES_DATA.

# Refuse to run anywhere but inside a claude_sandbox container, unless explicitly opted in.
[ -f /etc/claude-sandbox ] || [ "${1:-}" = "--i-know-this-modifies-my-system" ] || { echo "refusing: not inside a claude_sandbox container (to run it on your own machine, pass --i-know-this-modifies-my-system; see the header)" >&2; exit 1; }

set -euo pipefail

ARDUINO_CLI_VERSION=0.33.0   # the version py32duino's own CI uses
CORE=PY32Duino:PY32@0.1.3
INDEX_URL=https://github.com/PY32Duino/Arduino-pack-json-ci/releases/download/Nightly/package_py32_index.json
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ "$(uname -s)" = Linux ] || { echo "unsupported OS: $(uname -s) (Linux only)" >&2; exit 1; }
for tool in curl tar sha256sum python3; do
  command -v "$tool" >/dev/null || { echo "missing prerequisite: $tool" >&2; exit 1; }
done

if [ -f /etc/claude-sandbox ]; then
  HOST_MODE=0
  BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
else
  HOST_MODE=1
  TOOLS="$ROOT/.tools"
  BIN_DIR="${BIN_DIR:-$TOOLS/bin}"
  export ARDUINO_DIRECTORIES_DATA="$TOOLS/arduino15"
  export ARDUINO_DIRECTORIES_USER="$TOOLS/arduino-user"
  export ARDUINO_DIRECTORIES_DOWNLOADS="$TOOLS/arduino-downloads"   # separate setting; defaults to ~/.arduino15/staging
  mkdir -p "$ARDUINO_DIRECTORIES_DATA" "$ARDUINO_DIRECTORIES_USER" "$ARDUINO_DIRECTORIES_DOWNLOADS"
fi

arch="$(uname -m)"
case "$arch" in
  x86_64)  asset=Linux_64bit ;;
  aarch64) asset=Linux_ARM64 ;;
  *) echo "unsupported architecture: $arch" >&2; exit 1 ;;
esac

# Reuse an arduino-cli of the pinned version if one is already on PATH (an earlier run, or a system
# install); otherwise install our own into BIN_DIR, which comes first on PATH so it wins.
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

# Never rewrite a real machine's arduino-cli config: on your own machine the ARDUINO_DIRECTORIES_* variables
# above are enough.
if [ "$HOST_MODE" = 0 ]; then
  arduino-cli config init --overwrite >/dev/null 2>&1 || true
fi
arduino-cli core update-index --additional-urls "$INDEX_URL"
arduino-cli core install "$CORE" --additional-urls "$INDEX_URL"

# pyocd and pyftdi are pinned in constraints.txt (shared with CI); re-applied on every run so an
# older venv moves to the pinned versions when the pin changes.
PIP_CONSTRAINT="$ROOT/constraints.txt"
export PIP_CONSTRAINT
if [ ! -x "$ROOT/.venv/bin/pyocd" ]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q --upgrade pip
fi
"$ROOT/.venv/bin/pip" install -q pyocd                         # stack A needs only pyocd
# Second supported probe stack: FT232R bit-bang plugin (probes/ft232r). Both stacks stay supported;
# see "Probe parity" in CLAUDE.md. Editable, so edits to the plugin take effect without reinstalling.
"$ROOT/.venv/bin/pip" install -q -e "$ROOT/probes/ft232r"
"$ROOT/.venv/bin/pyocd" pack update >/dev/null 2>&1 || true
"$ROOT/.venv/bin/pyocd" pack install py32f030x8 || echo "note: pack install failed; run '.venv/bin/pyocd pack find py32f030' and install the match" >&2

if [ "$HOST_MODE" = 0 ]; then
  cat <<EOF

Done. Add to your shell:   export PATH="$BIN_DIR:$ROOT/.venv/bin:\$PATH"
Then:                      python3 tools/lb_flash.py build
EOF
else
  cat <<EOF

Done. Nothing was installed outside $ROOT except pip's and pyocd's package caches.
Add to your shell:
  export PATH="$BIN_DIR:$ROOT/.venv/bin:\$PATH"
  export ARDUINO_DIRECTORIES_DATA="$ARDUINO_DIRECTORIES_DATA" ARDUINO_DIRECTORIES_USER="$ARDUINO_DIRECTORIES_USER" ARDUINO_DIRECTORIES_DOWNLOADS="$ARDUINO_DIRECTORIES_DOWNLOADS"
Then:  python3 tools/lb_flash.py build
EOF
fi
