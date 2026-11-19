#!/usr/bin/env bash
# Installs everything lb_flash.py needs, without root and without distro packages:
#   - arduino-cli (pinned, checksum-verified release tarball)
#   - the py32duino core (+ its toolchain and CMSIS) via arduino-cli
#   - a Python venv (lightning_bugs/.venv) with pyocd (version pinned in constraints.txt)
# Safe to re-run. See assessments/toolchain.md for why.
#
# Pre-downloaded bundles: if ~/software (override with SOFTWARE_DIR) holds any of the files listed in the
# checksum table below, and their sha256 matches the pin, they are used instead of downloading them. Anything
# missing or with a different hash is ignored (with a note) and fetched normally. In a sandbox,
# claude_sandbox_host.yaml `files:` places them there from the host's ~/software.
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
SOFTWARE_DIR="${SOFTWARE_DIR:-$HOME/software}"

# sha256 of the bundles that may be pre-downloaded into SOFTWARE_DIR. Keep in step with claude_sandbox_host.yaml.
# Sources: arduino-cli's 0.33.0-checksums.txt, and the SHA-256 fields of the core index (core, gcc, CMSIS).
# The Puya pack publishes no checksum: this is the hash of our own download.
declare -A PINNED_SHA256=(
  [arduino-cli_0.33.0_Linux_64bit.tar.gz]=0eeaba59a345f4d2aab03d4412dd490e5a4db0d006be6c0a72f23df0ed7ecab9
  [arduino-cli_0.33.0_Linux_ARM64.tar.gz]=c7280677cf0cb12cd143813b7e97f832e86b49f8b39ba31ff65189ae1e577a51
  [Arduino-PY32-0.1.3.zip]=d18af465e4b81b575f009aa08fe77ecb506d2ae21cb96c2fb29c936cc12262c4
  [xpack-arm-none-eabi-gcc-13.2.1-1.1-linux-x64.tar.gz]=1252a8cafe9237de27a765376697230368eec21db44dc3f1edeb8d838dabd530
  [xpack-arm-none-eabi-gcc-13.2.1-1.1-linux-arm64.tar.gz]=ab7f75d95ead0b1efb7432e7f034f9575cc3d23dc1b03d41af1ec253486d19de
  [CMSIS-5.7.0.tar.bz2]=0b04b0f214e483bcc360cda985cddc0de8031714019ceabcda4770d510b82bfe
  [Puya.PY32F0xx_DFP.1.2.8.pack]=bb434a82e1a07973b3dcd9045a21748fa390b14c36fc90b9d27b4d005b65b566
)

# predownloaded NAME: print the path of SOFTWARE_DIR/NAME and succeed if it exists and matches its pin;
# otherwise succeed never (and say why, unless the file is simply absent).
predownloaded() {
  local f="$SOFTWARE_DIR/$1" want="${PINNED_SHA256[$1]:-}"
  [ -f "$f" ] || return 1
  [ -n "$want" ] || return 1
  if [ "$(sha256sum "$f" | awk '{print $1}')" = "$want" ]; then
    printf '%s\n' "$f"
  else
    echo "note: ignoring $f (sha256 does not match the pin); downloading instead" >&2
    return 1
  fi
}

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
  x86_64)  asset=Linux_64bit; gcc_asset=linux-x64 ;;
  aarch64) asset=Linux_ARM64; gcc_asset=linux-arm64 ;;
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
  if local_tarball="$(predownloaded "$tarball")"; then
    echo "Using pre-downloaded $local_tarball"
    cp "$local_tarball" "$tmp/$tarball"
  else
    echo "Downloading $tarball"
    curl -fsSL -o "$tmp/$tarball" "$base/$tarball"
    curl -fsSL -o "$tmp/checksums.txt" "$base/${ARDUINO_CLI_VERSION}-checksums.txt"
    (cd "$tmp" && grep " $tarball\$" checksums.txt | sha256sum -c -)
  fi
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
# Pre-seed arduino-cli's download staging dir: it reuses a file there ("already downloaded") when the name and
# the checksum from the index match, so the big archives are not fetched again. (The index itself is always
# fetched: it is small and it carries the checksums arduino-cli verifies against. AirISP is not pre-seeded.)
STAGING="${ARDUINO_DIRECTORIES_DOWNLOADS:-$HOME/.arduino15/staging}"
for name in Arduino-PY32-0.1.3.zip "xpack-arm-none-eabi-gcc-13.2.1-1.1-${gcc_asset}.tar.gz" CMSIS-5.7.0.tar.bz2; do
  if src="$(predownloaded "$name")"; then
    echo "Using pre-downloaded $src"
    mkdir -p "$STAGING/packages"
    cp "$src" "$STAGING/packages/$name"
  fi
done
arduino-cli core update-index --additional-urls "$INDEX_URL"
arduino-cli core install "$CORE" --additional-urls "$INDEX_URL"

# pyocd is pinned in constraints.txt (shared with CI); re-applied on every run so an
# older venv moves to the pinned versions when the pin changes.
PIP_CONSTRAINT="$ROOT/constraints.txt"
export PIP_CONSTRAINT
if [ ! -x "$ROOT/.venv/bin/pyocd" ]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q --upgrade pip
fi
"$ROOT/.venv/bin/pip" install -q pyocd
"$ROOT/.venv/bin/pyocd" pack update >/dev/null 2>&1 || true
# pyocd keeps packs as <data dir>/cmsis-pack-manager/<vendor>/<family>/<version>.pack and does not fetch one
# that is already there, so put the pre-downloaded Puya pack in place (never over an existing one).
if pack="$(predownloaded Puya.PY32F0xx_DFP.1.2.8.pack)"; then
  pack_dir="${XDG_DATA_HOME:-$HOME/.local/share}/cmsis-pack-manager/Puya/PY32F0xx_DFP"
  if [ ! -e "$pack_dir/1.2.8.pack" ]; then
    echo "Using pre-downloaded $pack"
    mkdir -p "$pack_dir"
    cp "$pack" "$pack_dir/1.2.8.pack"
  fi
fi
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
