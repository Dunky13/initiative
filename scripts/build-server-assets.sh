#!/usr/bin/env bash
# Build test server assets from source, signed with a key made for this build.
# Release packages take theirs from the checked image (server-packages.yml).
set -euo pipefail

usage() {
  echo 'Usage: build-server-assets.sh --output DIR' >&2
  exit 2
}
output=
while (( $# )); do
  case "$1" in
    --output) (( $# >= 2 )) || usage; output=$2; shift 2 ;;
    *) usage ;;
  esac
done
[[ -n "$output" ]] || usage
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
[[ ! -e "$output" ]] || { echo 'Asset output must not already exist.' >&2; exit 1; }
mkdir -p "$(dirname "$output")"
output=$(cd "$(dirname "$output")" && pwd)/$(basename "$output")
work=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/initiative-server-assets.XXXXXX")
trap 'rm -rf "$work"' EXIT
umask 077

key="$work/ota-test.pem"
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$key"
node --input-type=module - "$key" > "$work/public-key" <<'NODE'
import { createPrivateKey, createPublicKey } from 'node:crypto';
import { readFileSync } from 'node:fs';
const privateKey = createPrivateKey(readFileSync(process.argv[2]));
console.log(createPublicKey(privateKey).export({ type: 'spki', format: 'der' }).toString('base64'));
NODE

export VITE_API_URL=/api/v1
# A test payload names itself as one, and only an app trusting its key takes it.
export VITE_VERSION_SUFFIX="-server-test-${GITHUB_SHA:-local}"
VITE_OTA_DEV_PUBLIC_KEY=$(cat "$work/public-key")
export VITE_OTA_DEV_PUBLIC_KEY
cd "$root/frontend"
pnpm build
mkdir -p "$work/payload/browser" "$work/payload/editor" "$work/payload/ota"
cp -R dist/. "$work/payload/browser/"
pnpm build:editor-server
cp dist-editor/editor.js "$work/payload/editor/editor.js"
pnpm build:capacitor
(cd dist && zip -qr "$work/payload/ota/bundle.zip" .)
node --input-type=module - "$work/payload/ota/bundle.zip" > "$work/payload/ota/bundle.sha256" <<'NODE'
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
console.log(createHash('sha256').update(readFileSync(process.argv[2])).digest('hex'));
NODE
node scripts/sign-ota.mjs "$work/payload/ota" "$(cat "$root/VERSION")${VITE_VERSION_SUFFIX}" \
  "$(cat "$root/MIN_NATIVE_VERSION")" "$(cat "$root/MIN_DESKTOP_VERSION")" "$key"
for file in browser/index.html editor/editor.js ota/bundle.zip ota/bundle.sha256 ota/statement.json ota/statement.sig; do
  [[ -s "$work/payload/$file" ]] || { echo "Missing asset: $file" >&2; exit 1; }
done
# Ordinary public payload permissions; the temporary private key remains mode 0600.
chmod -R u=rwX,go=rX "$work/payload"
mv "$work/payload" "$output"
