# Rooster — werkafspraken

Home Assistant add-on: MyManus-rooster, uren en een geschat salaris.
Flask + SQLite + waitress. De rekenregels, de API en de pagina's zitten apart,
omdat de salarisberekening en de sync zonder de webserver testbaar moeten zijn.

- `rooster_app/app/datums.py` — dagnummers en ISO-weken
- `rooster_app/app/salaris.py` — contractperioden, toeslag, pensioen, loonheffing
- `rooster_app/app/agenda.py` — ICS
- `rooster_app/app/manus.py` — read-only client
- `rooster_app/app/synchronisatie.py` — ophalen en bewaren
- `rooster_app/app/opslag.py` — SQLite in `/data`
- `rooster_app/app/overzicht.py` — van database naar het maandscherm
- `rooster_app/app/main.py` — pagina's

Geen build-stap en geen frontend-framework: server-side Jinja, CSS in de layout.

## Draaien en testen

Er is geen venv in de repo. Zelf een maken:

```bash
python3 -m venv .venv
.venv/bin/pip install -r rooster_app/app/requirements.txt \
                     -r rooster_app/tests/requirements.txt
```

Tests draaien vanaf de hoofdmap (`pytest.ini` wijst naar `rooster_app/tests`):

```bash
.venv/bin/python -m pytest
```

De app lokaal starten met een eigen datamap, zodat je niet in `/data` schrijft.
De zijbalk-check sla je alleen over door het ingress-netwerk op je eigen machine
te zetten én de header mee te sturen. De header alleen is niet genoeg.

```bash
INGRESS_NETWERK=127.0.0.0/8 DATA_DIR=/tmp/rooster-demo PORT=8099 \
  .venv/bin/python rooster_app/app/main.py
```

Zet `INGRESS_NETWERK` nooit in `config.yaml` of in een script dat meegaat naar
Home Assistant: daar hoort alleen het standaardnetwerk te gelden.

`config.yaml` en de constante `VERSIE` in `main.py` horen hetzelfde versienummer
te hebben.

## Afspraken

- **Alles in het Nederlands**: variabelen, functienamen, commentaar, meldingen
  aan de gebruiker en commitberichten. Ook de tests, inclusief de testnamen.
- **Commentaar legt uit waaróm**, niet wat er staat.
- **Meldingen aan de gebruiker zijn gewone taal.**
- **Elke wijziging krijgt tests.**
- **Geen persoonsgegevens in de repository.** Geen namen, personeelsnummers,
  wachtwoorden, tokens of een echt uurloon. Het rekenvoorbeeld met een
  all-in maandstrook staat alleen in de tests, als verhoudingen, en is niet
  het uurloon waarmee de app start. Echte gegevens horen in de add-onopties
  of in `/data`.
- **Alleen lezen.** `ManusClient` weigert elke POST behalve de token-aanvraag,
  en elke andere methode. De sync mag dat niet omzeilen.

### Valkuil bij de tests

`conftest.py` maakt de database schoon tussen tests via `TABELLEN`. Voeg je een
tabel toe, zet hem daar dan meteen bij, anders lekt data van de ene test naar
de andere.

### Valkuil bij de datums

MyManus-dagnummer 46303 is 10 oktober 2026. Dat is twee dagen later dan
`30 december 1899 + n`. De app rekent vanaf 1 januari 1900. Niet "verbeteren"
naar het Excel-nulpunt: dan schuift het hele rooster.

ISO-weekjaar en kalenderjaar lopen uiteen. 1 januari 2021 hoort bij week 53
van 2020. De API verwacht het weekjaar.

## Uitbrengen

Bij een push naar `main` bouwt de CI het image; Home Assistant biedt de update
daarna zelf aan. De add-on heeft bewust geen `image` in `config.yaml`, zodat
de Supervisor hem lokaal bouwt. Zet in `CHANGELOG.md` wat er voor de gebruiker
verandert, in gewone taal.
