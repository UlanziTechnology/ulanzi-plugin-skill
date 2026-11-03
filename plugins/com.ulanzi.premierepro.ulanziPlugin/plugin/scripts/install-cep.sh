#!/bin/sh
set -eu
enable_debug=0
case "${1-}" in '') ;; --enable-debug) enable_debug=1 ;; *) printf '%s\n' 'Usage: sh install-cep.sh [--enable-debug]' >&2; exit 2 ;; esac
[ "$(uname -s)" = Darwin ] || { printf '%s\n' 'This installer is for macOS.' >&2; exit 1; }
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
source_dir=$(CDPATH= cd -- "$script_dir/../cep/com.ulanzi.premierepro.bridge" && pwd -P)
[ -f "$source_dir/CSXS/manifest.xml" ] || { printf '%s\n' 'CEP extension source is missing.' >&2; exit 1; }
user_home=$(CDPATH= cd -- "$HOME" && pwd -P)
extension_root="$user_home/Library/Application Support/Adobe/CEP/extensions"
backup_root="$user_home/Library/Application Support/Adobe/CEP/UlanziBackups"
mkdir -p "$extension_root" "$backup_root"
[ "$(CDPATH= cd -- "$extension_root" && pwd -P)" = "$extension_root" ] || { printf '%s\n' 'Refusing a linked installation directory.' >&2; exit 1; }
[ "$(CDPATH= cd -- "$backup_root" && pwd -P)" = "$backup_root" ] || { printf '%s\n' 'Refusing a linked backup directory.' >&2; exit 1; }
target="$extension_root/com.ulanzi.premierepro.bridge"
backup="$backup_root/com.ulanzi.premierepro.bridge-$(date +%Y%m%d-%H%M%S)-$$"
[ ! -L "$target" ] || { printf '%s\n' 'Refusing to replace a linked extension.' >&2; exit 1; }
case "$target" in "$user_home/Library/Application Support/Adobe/CEP/extensions/com.ulanzi.premierepro.bridge") ;; *) exit 1 ;; esac
if [ -e "$target" ]; then mv "$target" "$backup"; fi
if ! cp -R "$source_dir" "$target"; then
  if [ -e "$target" ]; then mv "$target" "$backup-failed"; fi
  if [ -e "$backup" ]; then mv "$backup" "$target"; fi
  exit 1
fi
if [ "$enable_debug" = 1 ]; then
  defaults write com.adobe.CSXS.11 PlayerDebugMode 1
  defaults write com.adobe.CSXS.12 PlayerDebugMode 1
  printf '%s\n' 'Unsigned CEP development extensions enabled for CSXS 11 and 12 (all extensions for this user).'
fi
printf 'CEP extension installed: %s\n' "$target"
if [ -e "$backup" ]; then printf 'Previous extension preserved: %s\n' "$backup"; fi
printf '%s\n' 'Save your project and restart Premiere Pro. The background bridge connects automatically; no panel needs to stay open.' 'For troubleshooting only: Window > Extensions > Ulanzi Premiere Bridge Diagnostics.' 'The Ulanzi plugin itself has not been installed or synchronized by this script.'
