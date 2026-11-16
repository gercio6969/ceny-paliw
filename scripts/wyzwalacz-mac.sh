#!/usr/bin/env bash
# Niezawodny wyzwalacz aktualizacji cen paliw z Maca (launchd).
#
# Harmonogram GitHub Actions bywa opóźniany o godziny albo pomijany, więc Mac co 15 minut
# w dni robocze (10:00–18:45) prosi GitHuba o uruchomienie workflow przez `gh`.
# Dane rynkowe pobierane są tylko o pełnej godzinie. Uśpiony Mac nadrobi jedno
# uruchomienie po wybudzeniu.
#
# Użycie:
#   ./scripts/wyzwalacz-mac.sh instaluj    # instaluje i od razu uruchamia jedno sprawdzenie
#   ./scripts/wyzwalacz-mac.sh usun        # wyłącza i usuwa wyzwalacz
#   ./scripts/wyzwalacz-mac.sh teraz       # jednorazowe sprawdzenie cen
#   ./scripts/wyzwalacz-mac.sh status      # czy działa + ostatnie wpisy z logu
#
# Autor: Gerard Modlewski
set -euo pipefail

REPO="gercio6969/ceny-paliw"
LABEL="pl.gerardmodlewski.ceny-paliw"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/ceny-paliw-wyzwalacz.log"
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

find_gh() {
  for candidate in "$(command -v gh 2>/dev/null || true)" /opt/homebrew/bin/gh /usr/local/bin/gh; do
    [[ -n "$candidate" && -x "$candidate" ]] && { echo "$candidate"; return; }
  done
  echo "Nie znaleziono gh. Zainstaluj: brew install gh" >&2
  exit 1
}

trigger() {
  local gh market="false"
  gh="$(find_gh)"
  [[ "$(date +%M)" == "00" || "${1:-}" == "z-rynkiem" ]] && market="true"
  echo "$(date '+%F %T') uruchamiam (rynek: $market)"
  "$gh" workflow run update-and-deploy.yml --repo "$REPO" -f market="$market"
}

install() {
  local gh
  gh="$(find_gh)"
  "$gh" auth status >/dev/null 2>&1 || { echo "Najpierw: gh auth login" >&2; exit 1; }
  mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"

  # Kopia skryptu poza folderem Pobrane (launchd nie ma tam domyślnie dostępu).
  local target="$HOME/Library/Application Support/ceny-paliw/wyzwalacz-mac.sh"
  mkdir -p "$(dirname "$target")"
  cp "$SELF" "$target"
  chmod 755 "$target"

  {
    cat <<XML
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$target</string>
    <string>uruchom</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$(dirname "$gh"):/usr/bin:/bin</string></dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>StartCalendarInterval</key>
  <array>
XML
    for weekday in 1 2 3 4 5; do
      for hour in 10 11 12 13 14 15 16 17 18; do
        for minute in 0 15 30 45; do
          printf '    <dict><key>Weekday</key><integer>%d</integer><key>Hour</key><integer>%d</integer><key>Minute</key><integer>%d</integer></dict>\n' \
            "$weekday" "$hour" "$minute"
        done
      done
    done
    cat <<XML
  </array>
</dict>
</plist>
XML
  } > "$PLIST"
  plutil -lint "$PLIST" >/dev/null

  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "Wyzwalacz zainstalowany: co 15 min, pon–pt 10:00–18:45. Log: $LOG"
  trigger z-rynkiem
}

remove() {
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  rm -rf "$HOME/Library/Application Support/ceny-paliw"
  echo "Wyzwalacz usunięty."
}

case "${1:-}" in
  instaluj) install ;;
  usun) remove ;;
  uruchom) trigger ;;
  teraz) trigger z-rynkiem ;;
  status)
    launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 && echo "Działa." || echo "Nie zainstalowany."
    [[ -f "$LOG" ]] && tail -n 5 "$LOG" || true
    ;;
  *) sed -n '2,15p' "$0"; exit 1 ;;
esac
