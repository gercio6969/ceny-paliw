#!/usr/bin/env bash
# Przypina akcje GitHuba w .github/workflows do pełnych SHA commitów.
#
# Tag (np. @v4) można przesunąć na inny commit; SHA nie. Skrypt pyta GitHuba przez `gh`
# o commit, na który wskazuje tag, i zamienia `uses: owner/repo@v4` na
# `uses: owner/repo@<sha> # v4`. Dependabot aktualizuje potem SHA razem z komentarzem.
#
# Autor: Gerard Modlewski
set -euo pipefail

cd "$(dirname "$0")/.."
command -v gh >/dev/null || { echo "Wymagane GitHub CLI (gh)" >&2; exit 1; }

shopt -s nullglob
for file in .github/workflows/*.yml; do
  # tylko wpisy z tagiem, jeszcze nie przypięte do SHA
  { grep -oE 'uses: [A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@v[0-9][A-Za-z0-9.]*' "$file" || true; } | sort -u |
  while read -r _ ref; do
    action="${ref%@*}"
    tag="${ref#*@}"
    repo="$(cut -d/ -f1-2 <<<"$action")"
    sha="$(gh api "repos/$repo/commits/$tag" --jq .sha)"
    if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
      echo "Nie udało się ustalić SHA dla $ref" >&2
      exit 1
    fi
    echo "$ref -> $sha"
    # separator '|' – w nazwach akcji nie występuje
    sed -i.bak "s|uses: $action@$tag\$|uses: $action@$sha # $tag|" "$file"
    rm -f "$file.bak"
  done
done
