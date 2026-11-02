#!/bin/bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
BUILD_PYTHON="${CODEX_SYNC_BUILD_PYTHON:-python3.11}"
if [ ! -x .venv-build/bin/python ]; then
  "$BUILD_PYTHON" -m venv .venv-build
fi
.venv-build/bin/python -m pip install . pyinstaller==6.14.2 pillow > .venv-build/install.log 2>&1
.venv-build/bin/python scripts/generate_icons.py
.venv-build/bin/python -m PyInstaller --noconfirm --clean --windowed \
  --icon assets/icon.icns --add-data assets/icon.icns:assets --add-data assets/icon.png:assets \
  --name 'Codex Sync Desktop' --osx-bundle-identifier com.cieyyy.codex-sync-desktop \
  launch.py > .venv-build/build.log 2>&1
.venv-build/bin/python - <<'PY'
import plistlib
from pathlib import Path
path = Path('dist/Codex Sync Desktop.app/Contents/Info.plist')
data = plistlib.loads(path.read_bytes())
data['CFBundleShortVersionString'] = '1.0.0'
data['CFBundleVersion'] = '1.0.0.1'
data['CodexSyncLocalBuild'] = '1.0.0'
path.write_bytes(plistlib.dumps(data))
PY
xattr -cr 'dist/Codex Sync Desktop.app'
codesign --force --deep --sign - 'dist/Codex Sync Desktop.app'
codesign --verify --deep --strict 'dist/Codex Sync Desktop.app'
'dist/Codex Sync Desktop.app/Contents/MacOS/Codex Sync Desktop' --smoke-ui
'dist/Codex Sync Desktop.app/Contents/MacOS/Codex Sync Desktop' --smoke-onboarding
'dist/Codex Sync Desktop.app/Contents/MacOS/Codex Sync Desktop' --smoke-import-preview
.venv-build/bin/python scripts/verify_macos_documents.py 'dist/Codex Sync Desktop.app' build/macos-document-verification
STAGING_DIR="$(mktemp -d "$PROJECT_ROOT/build/macos-dmg.XXXXXX")"
ditto 'dist/Codex Sync Desktop.app' "$STAGING_DIR/Codex Sync Desktop.app"
ln -s /Applications "$STAGING_DIR/Applications"
PACKAGE_PATH="dist/Codex-Sync-Desktop-v1.0.0-macOS-local.dmg"
hdiutil create -volname 'Codex Sync Desktop' -srcfolder "$STAGING_DIR" -ov -format UDZO "$PACKAGE_PATH"
hdiutil verify "$PACKAGE_PATH"
shasum -a 256 "$PACKAGE_PATH" > dist/SHA256SUMS-v1.0.0-local.txt
