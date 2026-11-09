# Ceny paliw

Autor: **Gerard Modlewski**

Aplikacja na telefon (PWA, bez App Store i Google Play) pokazująca **maksymalne ceny paliw** ogłaszane codziennie przez Ministra Energii w Monitorze Polskim: benzyna 95, benzyna 98 i olej napędowy, z historią zmian.

## Jak to działa

```
api.sejm.gov.pl (ELI)          GitHub Actions (dni robocze, co 20 min)          GitHub Pages
obwieszczenie MP, PDF  ──►  python -m fuelprices  ──►  data/prices.json  ──►  PWA na telefonie
```

1. **Scraper** (`src/fuelprices`) szuka obwieszczeń „w sprawie maksymalnej ceny paliw ciekłych na stacji paliw” w dwóch oficjalnych źródłach, pobiera nowe PDF-y, odczytuje ceny netto (zł/dm³) i z VAT (zł/l) i dopisuje je do `data/prices.json`:
   - **monitorpolski.gov.pl** (Rządowe Centrum Legislacji) – obwieszczenie jest tam w dniu ogłoszenia, więc aplikacja zna cenę na jutro od razu po publikacji;
   - **API ELI Sejmu** – pełna historia, ale akty pojawiają się z opóźnieniem jednego dnia roboczego, więc służy do uzupełniania historii i jako zapas.
2. **Workflow** `update-and-deploy.yml` uruchamia scraper, zapisuje zmiany commitem bota i publikuje stronę na GitHub Pages.
3. **Dane rynkowe** (`src/fuelprices/market.py`) zapisuje do `data/market.json`: ropę Brent, kurs USD/PLN z NBP, hurtowe ceny ORLEN i kurs akcji ORLEN.
4. **PWA** (`web/`) czyta oba pliki, działa offline (service worker) i da się ją dodać do ekranu głównego.

Ceny obowiązują od dnia następującego po ogłoszeniu obwieszczenia. Aplikacja pokazuje dwie kolumny: **Dziś** i **Jutro**. Cena na jutro pojawia się, gdy obwieszczenie trafi do Monitora Polskiego. W sobotę i niedzielę jest znana z góry, bo piątkowe obwieszczenie obowiązuje do poniedziałku włącznie.

### Źródła danych rynkowych

| Dane | Źródło | Uwagi |
|---|---|---|
| Kurs USD/PLN | API NBP, tabela A | oficjalne |
| Ropa Brent | Yahoo Finance (`BZ=F`), zapasowo FRED | nieoficjalne / FRED z opóźnieniem kilku dni |
| Hurt ORLEN | `tool.orlen.pl/api/wholesalefuelprices` | nieoficjalne API strony ORLEN, zł/m³ netto |
| Akcje ORLEN | Yahoo Finance (`PKN.WA`) | nieoficjalne |

Każde źródło pobierane jest osobno. Gdy któreś nie odpowiada, zostaje ostatnia znana wartość oznaczona w aplikacji jako nieaktualna, a ceny paliw aktualizują się normalnie.

## Instalacja na telefonie

- **iPhone (Safari):** otwórz adres aplikacji → *Udostępnij* → *Do ekranu początkowego*.
- **Android (Chrome):** otwórz adres → przycisk *Zainstaluj aplikację* albo menu ⋮ → *Dodaj do ekranu głównego*.

Adres: `https://<login>.github.io/ceny-paliw/`

## Publikacja na GitHubie

Wymaga [GitHub CLI](https://cli.github.com) zalogowanego na Twoje konto (`gh auth login`):

```bash
./publish.sh             # repo publiczne – GitHub Pages za darmo
./publish.sh --private   # repo prywatne – Pages wymaga planu GitHub Pro
```

Skrypt przypina akcje GitHuba do SHA, ustawia autora commitów na Gerard Modlewski (także dla automatycznych commitów z danymi), tworzy repozytorium, włącza zabezpieczenia GitHuba i Pages (źródło: GitHub Actions), a na koniec uruchamia pierwsze pobranie z historią ~60 obwieszczeń.

Ręcznie: *Settings → Pages → Source: GitHub Actions*, potem *Actions → Aktualizacja cen i publikacja → Run workflow*.

## Rozwój lokalny

```bash
python -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt

pytest                      # testy
ruff check . && ruff format --check .
PYTHONPATH=src python -m fuelprices -v     # pobranie najnowszych obwieszczeń do data/prices.json
PYTHONPATH=src python -m fuelprices.market # dane rynkowe do data/market.json

# podgląd aplikacji
mkdir -p _site/data && cp -r web/. _site/ && cp data/*.json _site/data/
python -m http.server -d _site 8000
```

Zależności są zablokowane z hashami. Po zmianie `pyproject.toml` wygeneruj je ponownie:

```bash
uv pip compile --generate-hashes --universal --python-version 3.12 pyproject.toml -o requirements.txt
uv pip compile --generate-hashes --universal --python-version 3.12 --extra dev pyproject.toml -o requirements-dev.txt
```

Po zmianie plików w `web/` podbij `VERSION` w `web/sw.js`, żeby telefony pobrały nową wersję. Ikony generuje `python scripts/make_icons.py`.

## Gdy coś się zepsuje

Jeśli ministerstwo zmieni format obwieszczenia, parser odmówi zapisu (sprawdza obecność wszystkich paliw, realny zakres cen i to, że cena z VAT jest wyższa od netto). Workflow zakończy się błędem, a GitHub wyśle e-mail. Wcześniejsze dane pozostają nietknięte.

Wtedy: pobierz PDF z logu workflow, dodaj jego tekst jako fixture w `tests/fixtures/` i popraw wyrażenia w `src/fuelprices/parser.py`.

## Format danych

`data/prices.json`:

```json
{
  "schema": 1,
  "updated_at": "2026-11-09T13:00:00+00:00",
  "latest": {
    "eli": "MP/2026/1065",
    "position": 1065,
    "announced": "2026-11-02",
    "valid_from": "2026-11-03",
    "source_url": "https://api.sejm.gov.pl/eli/acts/MP/2026/1065/text.pdf",
    "prices": {
      "pb95": { "net": 5.98, "gross": 6.45 },
      "pb98": { "net": 6.77, "gross": 7.31 },
      "on":   { "net": 7.53, "gross": 8.14 }
    }
  },
  "history": [ "… te same obiekty, od najnowszego …" ]
}
```

## Bezpieczeństwo

Opis zabezpieczeń i sposób zgłaszania podatności: [SECURITY.md](SECURITY.md).

## Licencja

MIT © 2026 Gerard Modlewski
