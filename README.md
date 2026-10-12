# Rooster — Home Assistant add-on repository

Home Assistant add-on repository met **Rooster**: je MyManus-rooster, uren,
verlofsaldo en een geschat salaris in de zijbalk, en je diensten in een
gedeelde iCloud-agenda.

MyManus is de medewerkers-app van MANUS Workforce Management. Deze add-on leest
alleen. Er wordt niets teruggeschreven naar het rooster.

## Toevoegen aan Home Assistant

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fstsanders06%2Frooster-app)

Of handmatig:

1. **Instellingen → Add-ons → Add-on Store**
2. Rechtsboven de drie puntjes → **Repositories**
3. Plak `https://github.com/stsanders06/rooster-app` en klik **Toevoegen**
4. Installeer de add-on **Rooster** en start hem
5. Zet **Show in sidebar** aan. Het rooster open je via de zijbalk.

## Add-ons in deze repository

| Add-on | Beschrijving |
| --- | --- |
| [Rooster](./rooster_app) | Rooster, uren, verlofsaldo, geschat salaris en een iCloud-agenda vanuit MyManus |

Zie [de documentatie](./rooster_app/DOCS.md) voor installatie, de salarisperioden
en de iCloud-agenda.

## Ondersteunde architecturen

`aarch64` en `amd64` — dus onder andere Raspberry Pi 3/4/5 (64-bit), Home Assistant
Green, Yellow en x86-installaties. `armv7` wordt niet ondersteund: Home Assistant
heeft die architectuur per 2025.12 uitgefaseerd.

## Licentie

[MIT](./LICENSE)
