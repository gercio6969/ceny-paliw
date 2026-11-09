# Bezpieczeństwo

Autor i opiekun projektu: **Gerard Modlewski**.

## Zgłaszanie podatności

Nie zgłaszaj podatności w publicznych Issues. Użyj prywatnego zgłoszenia:
zakładka **Security → Report a vulnerability** w tym repozytorium.

## Model zagrożeń i zabezpieczenia

Aplikacja nie ma backendu, kont użytkowników ani sekretów. Publikowane są wyłącznie statyczne pliki
i publiczne dane. Główne ryzyka to podmiana danych lub kodu w łańcuchu dostaw oraz złośliwe
odpowiedzi zewnętrznych źródeł.

| Obszar | Zabezpieczenie |
|---|---|
| Akcje GitHuba | przypięte do pełnych SHA (`scripts/pin-actions.sh`), aktualizowane przez Dependabot |
| Uprawnienia workflow | domyślnie brak (`permissions: {}`), każde zadanie dostaje minimum; domyślny token repo tylko do odczytu |
| Wstrzyknięcie poleceń | parametry z formularza przekazywane przez zmienne środowiskowe i walidowane (1–400) |
| Poświadczenia | `persist-credentials: false` tam, gdzie zadanie nie zapisuje do repo |
| Zależności Pythona | zablokowane wersje z hashami (`requirements*.txt`, `pip install --require-hashes`) |
| Odpowiedzi zewnętrzne | limit rozmiaru (5 MB), sprawdzenie sygnatury PDF i liczby stron, walidacja zakresów cen, odrzucanie NaN/∞ |
| Integralność danych | parser odmawia zapisu przy nieoczekiwanym formacie; zapis atomowy; poprzednie dane zostają |
| Frontend | Content Security Policy bez zewnętrznych zasobów i skryptów inline; dane wstawiane wyłącznie przez `textContent`; link do źródła tylko w obrębie `api.sejm.gov.pl` |
| Prywatność | brak analityki, ciasteczek i zapytań do zewnętrznych serwerów z telefonu; `no-referrer` |
| Repozytorium | alerty Dependabot, automatyczne poprawki bezpieczeństwa, skanowanie sekretów z blokadą pushowania |

## Znane ograniczenia

- GitHub Pages nie pozwala ustawiać nagłówków HTTP, więc część polityk (np. `frame-ancestors`)
  nie jest dostępna. CSP jest ustawione przez znacznik `<meta>`.
- Dane rynkowe (Yahoo Finance, API ORLEN) pochodzą z nieoficjalnych źródeł i mają charakter
  orientacyjny.
