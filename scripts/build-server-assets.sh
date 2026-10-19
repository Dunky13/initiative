#!/usr/bin/env bash
# Build the shared server payload from source; never extract it from an image.
set -euo pipefail

usage() {
  echo 'Usage: build-server-assets.sh --output DIR --channel release|dev [--signing-key FILE]' >&2
  exit 2
}
output=
channel=
key=
while (( $# )); do
  case "$1" in
    --output) (( $# >= 2 )) || usage; output=$2; shift 2 ;;
    --channel) (( $# >= 2 )) || usage; channel=$2; shift 2 ;;
    --signing-key) (( $# >= 2 )) || usage; key=$2; shift 2 ;;
    *) usage ;;
  esac
done
[[ -n "$output" && "$channel" =~ ^(release|dev)$ ]] || usage
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
[[ ! -e "$output" ]] || { echo 'Asset output must not already exist.' >&2; exit 1; }
mkdir -p "$(dirname "$output")"
output=$(cd "$(dirname "$output")" && pwd)/$(basename "$output")
work=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/initiative-server-assets.XXXXXX")
trap 'rm -rf "$work"' EXIT
umask 077

if [[ "$channel" == release ]]; then
  [[ -n "$key" && -s "$key" ]] || { echo 'Release assets require the production OTA signing key.' >&2; exit 1; }
else
  [[ -z "$key" ]] || { echo 'Dev/test assets always use an ephemeral key.' >&2; exit 1; }
  key="$work/ota-test.pem"
  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$key"
fi
# Fail before building if the production key is not trusted by the native apps.
# Only the SPKI public half leaves this process; no private key enters the payload.
node --input-type=module - "$key" "$root/frontend/src/lib/otaTrust.ts" "$channel" > "$work/public-key" <<'NODE'
import { createPrivateKey, createPublicKey } from 'node:crypto';
import { readFileSync } from 'node:fs';
const [keyFile, trustFile, channel] = process.argv.slice(2);
const privateKey = createPrivateKey(readFileSync(keyFile));
if (privateKey.asymmetricKeyType !== 'ec' || privateKey.asymmetricKeyDetails.namedCurve !== 'prime256v1') {
  throw new Error('OTA signing requires an ECDSA P-256 key');
}
const publicKey = createPublicKey(privateKey).export({ type: 'spki', format: 'der' }).toString('base64');
const declaration = readFileSync(trustFile, 'utf8').match(/const RELEASE_KEYS[^=]*=\s*\[([\s\S]*?)\];/);
if (channel === 'release' && (!declaration || ![...declaration[1].matchAll(/"([A-Za-z0-9+/=]+)"/g)].some((match) => match[1] === publicKey))) {
  throw new Error('OTA signing key is not in the native apps RELEASE_KEYS');
}
console.log(publicKey);
NODE

export VITE_API_URL=/api/v1
export VITE_VERSION_SUFFIX=
export VITE_OTA_DEV_PUBLIC_KEY=
if [[ "$channel" == dev ]]; then
  # A test payload must never masquerade as a release or update production apps.
  export VITE_VERSION_SUFFIX="-server-test-${GITHUB_SHA:-local}"
  VITE_OTA_DEV_PUBLIC_KEY=$(cat "$work/public-key")
  export VITE_OTA_DEV_PUBLIC_KEY
fi
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
