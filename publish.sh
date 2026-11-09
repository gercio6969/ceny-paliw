#!/usr/bin/env bash
# Jednorazowa publikacja projektu na GitHubie (konto zalogowane w `gh`).
# Wymaga: git, gh (https://cli.github.com) i `gh auth login`.
#
# Użycie:  ./publish.sh            # repo publiczne (GitHub Pages za darmo)
#          ./publish.sh --private  # repo prywatne (Pages wymaga planu GitHub Pro)
#
# Autor: Gerard Modlewski
set -euo pipefail
cd "$(dirname "$0")"

REPO_NAME="ceny-paliw"
AUTHOR_NAME="Gerard Modlewski"
VISIBILITY="--public"
[[ "${1:-}" == "--private" ]] && VISIBILITY="--private"

command -v gh >/dev/null || { echo "Zainstaluj GitHub CLI: brew install gh" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Zaloguj się: gh auth login" >&2; exit 1; }

OWNER="$(gh api user --jq .login)"
USER_ID="$(gh api user --jq .id)"
# Adres „noreply” GitHuba – commity są przypisane do konta bez ujawniania prywatnego e-maila.
AUTHOR_EMAIL="${USER_ID}+${OWNER}@users.noreply.github.com"
echo "Konto: $OWNER, autor commitów: $AUTHOR_NAME <$AUTHOR_EMAIL>"

# 1. Przypięcie akcji GitHuba do SHA (ochrona przed podmianą tagów)
./scripts/pin-actions.sh

# 2. Lokalne repozytorium z autorem Gerard Modlewski
if [[ ! -d .git ]]; then
  git init -q -b main
fi
git config user.name "$AUTHOR_NAME"
git config user.email "$AUTHOR_EMAIL"
git add .
git commit -q -m "Pierwsza wersja aplikacji Ceny paliw" || echo "Brak zmian do zatwierdzenia."

# 3. Repozytorium na GitHubie
gh repo create "$REPO_NAME" "$VISIBILITY" --source=. --remote=origin --push \
  --description "Maksymalne ceny paliw z obwieszczeń Ministra Energii jako aplikacja PWA"

# 4. Autor automatycznych commitów z danymi (zmienne repozytorium, nie sekrety)
gh variable set COMMIT_AUTHOR_NAME --repo "$OWNER/$REPO_NAME" --body "$AUTHOR_NAME"
gh variable set COMMIT_AUTHOR_EMAIL --repo "$OWNER/$REPO_NAME" --body "$AUTHOR_EMAIL"

# 5. Zabezpieczenia GitHuba: alerty o podatnościach, automatyczne poprawki zależności,
#    skanowanie sekretów z blokadą pushowania (dla repo publicznych)
gh api -X PUT "repos/$OWNER/$REPO_NAME/vulnerability-alerts" >/dev/null
gh api -X PUT "repos/$OWNER/$REPO_NAME/automated-security-fixes" >/dev/null
if [[ "$VISIBILITY" == "--public" ]]; then
  gh api -X PATCH "repos/$OWNER/$REPO_NAME" --input - >/dev/null <<'JSON' || true
{"security_and_analysis": {"secret_scanning": {"status": "enabled"},
                           "secret_scanning_push_protection": {"status": "enabled"}}}
JSON
fi
# Workflowy mogą domyślnie tylko czytać; zapis przyznają sobie jawnie w plikach .yml
gh api -X PUT "repos/$OWNER/$REPO_NAME/actions/permissions/workflow" \
  -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false >/dev/null

# 6. GitHub Pages publikowane przez GitHub Actions
gh api -X POST "repos/$OWNER/$REPO_NAME/pages" -f build_type=workflow >/dev/null 2>&1 \
  || gh api -X PUT "repos/$OWNER/$REPO_NAME/pages" -f build_type=workflow >/dev/null

# 7. Pierwsze pobranie z historią z ostatnich ~3 miesięcy
gh workflow run update-and-deploy.yml --repo "$OWNER/$REPO_NAME" -f backfill=60

echo
echo "Gotowe. Postęp: https://github.com/$OWNER/$REPO_NAME/actions"
echo "Aplikacja (po 2–3 min): https://$OWNER.github.io/$REPO_NAME/"
