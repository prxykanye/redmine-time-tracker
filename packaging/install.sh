#!/usr/bin/env bash
# Install Redmine Time Tracker for the current user, no root required.
set -euo pipefail

APP_NAME="redmine-time-tracker"
PREFIX="${PREFIX:-$HOME/.local}"
DATA_HOME="${XDG_DATA_HOME:-$PREFIX/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"

APP_DIR="$PREFIX/opt/$APP_NAME"
BIN_DIR="$PREFIX/bin"
APPLICATIONS="$DATA_HOME/applications"
ICON_ROOT="$DATA_HOME/icons/hicolor"
AUTOSTART_DIR="$CONFIG_HOME/autostart"

AUTOSTART=-1   # -1 leave as is, 1 install, 0 remove
UNINSTALL=0

usage() {
    cat <<'USAGE'
Usage: install.sh [options]

  --autostart      start the tracker in the tray when the session starts
  --no-autostart   remove an existing autostart entry
  --uninstall      remove the application and desktop integration
  -h, --help       show this help

Environment:
  PREFIX           install prefix, default: $HOME/.local
  XDG_DATA_HOME    overrides $PREFIX/share
  XDG_CONFIG_HOME  overrides $HOME/.config
USAGE
}

for argument in "$@"; do
    case "$argument" in
        --autostart) AUTOSTART=1 ;;
        --no-autostart) AUTOSTART=0 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help) usage; exit 0 ;;
        *)
            echo "Unknown option: $argument" >&2
            usage >&2
            exit 2
            ;;
    esac
done

refresh_caches() {
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$APPLICATIONS" >/dev/null 2>&1 || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1 && [ -f "$ICON_ROOT/index.theme" ]; then
        gtk-update-icon-cache -f -t "$ICON_ROOT" >/dev/null 2>&1 || true
    fi
}

remove_icons() {
    if [ -d "$ICON_ROOT" ]; then
        find "$ICON_ROOT" -type f -name "$APP_NAME.png" -delete 2>/dev/null || true
    fi
    rm -f "$ICON_ROOT/scalable/apps/$APP_NAME.svg"
}

remove_autostart() {
    rm -f "$AUTOSTART_DIR/$APP_NAME.desktop"
}

if [ "$UNINSTALL" = "1" ]; then
    rm -rf "$APP_DIR"
    rm -f "$BIN_DIR/$APP_NAME"
    rm -f "$APPLICATIONS/$APP_NAME.desktop"
    remove_icons
    remove_autostart
    refresh_caches
    STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
    cat <<EOF
Removed $APP_NAME.

User data was kept:
  $CONFIG_HOME/$APP_NAME
  $DATA_HOME/$APP_NAME
  $STATE_HOME/$APP_NAME
EOF
    exit 0
fi

if [ "$(uname -s)" != "Linux" ]; then
    echo "This bundle is built for Linux." >&2
    exit 1
fi
if [ "$(uname -m)" != "x86_64" ]; then
    echo "This bundle is built for x86_64 and will not run on $(uname -m)." >&2
    exit 1
fi

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -x "$SOURCE_DIR/app/$APP_NAME" ]; then
    echo "Broken bundle: $SOURCE_DIR/app/$APP_NAME is missing." >&2
    exit 1
fi

mkdir -p "$APP_DIR" "$BIN_DIR" "$APPLICATIONS" "$ICON_ROOT"

rm -rf "$APP_DIR/app"
cp -a "$SOURCE_DIR/app" "$APP_DIR/app"

cat > "$BIN_DIR/$APP_NAME" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/app/$APP_NAME" "\$@"
EOF
chmod 755 "$BIN_DIR/$APP_NAME"

sed "s|^Exec=.*|Exec=$BIN_DIR/$APP_NAME|" \
    "$SOURCE_DIR/$APP_NAME.desktop" > "$APPLICATIONS/$APP_NAME.desktop"

for png in "$SOURCE_DIR"/icons/appicon-*.png; do
    [ -e "$png" ] || continue
    file="${png##*/}"
    size="${file#appicon-}"
    size="${size%.png}"
    install -Dm644 "$png" "$ICON_ROOT/${size}x${size}/apps/$APP_NAME.png"
done
install -Dm644 "$SOURCE_DIR/$APP_NAME.svg" "$ICON_ROOT/scalable/apps/$APP_NAME.svg"

if [ "$AUTOSTART" = "1" ]; then
    mkdir -p "$AUTOSTART_DIR"
    sed "s|^Exec=.*|Exec=$BIN_DIR/$APP_NAME --minimized|" \
        "$SOURCE_DIR/$APP_NAME-autostart.desktop" > "$AUTOSTART_DIR/$APP_NAME.desktop"
elif [ "$AUTOSTART" = "0" ]; then
    remove_autostart
fi

if [ -f "$SOURCE_DIR/VERSION" ]; then
    install -Dm644 "$SOURCE_DIR/VERSION" "$APP_DIR/VERSION"
fi

refresh_caches

if [ "$AUTOSTART" = "1" ]; then
    AUTOSTART_STATE="enabled"
elif [ "$AUTOSTART" = "0" ]; then
    AUTOSTART_STATE="removed"
else
    AUTOSTART_STATE="unchanged"
fi

cat <<EOF
Installed $APP_NAME.

  launcher:  $BIN_DIR/$APP_NAME
  payload:   $APP_DIR
  menu item: $APPLICATIONS/$APP_NAME.desktop
  autostart: $AUTOSTART_STATE

Start it from the application menu or run:
  $BIN_DIR/$APP_NAME
EOF

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        echo
        echo "Note: $BIN_DIR is not in PATH. The menu item works without it."
        ;;
esac
