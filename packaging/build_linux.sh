#!/usr/bin/env bash
# Build the self-contained Linux bundle with PyInstaller.
set -euo pipefail

cd "$(dirname "$0")/.."

APP="redmine-time-tracker"
VERSION="$(uv run python -c 'from redmine_time_tracker import __version__; print(__version__)')"
BUNDLE="$APP-$VERSION-linux-x86_64"

rm -rf build dist
uv run --with pyinstaller pyinstaller --noconfirm --clean packaging/pyinstaller.spec

STAGE="dist/$BUNDLE"
mkdir -p "$STAGE"
cp -a "dist/$APP" "$STAGE/app"
cp packaging/install.sh \
   packaging/redmine-time-tracker.desktop \
   packaging/redmine-time-tracker-autostart.desktop \
   "$STAGE/"
cp -a src/redmine_time_tracker/resources/icons "$STAGE/icons"
cp src/redmine_time_tracker/resources/appicon.svg "$STAGE/$APP.svg"
printf '%s\n' "$VERSION" > "$STAGE/VERSION"
chmod +x "$STAGE/install.sh"

tar -C dist -czf "dist/$BUNDLE.tar.gz" "$BUNDLE"
du -h "dist/$BUNDLE.tar.gz"
echo "Built dist/$BUNDLE.tar.gz"
