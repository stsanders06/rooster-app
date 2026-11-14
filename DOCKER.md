# Rooster zonder Home Assistant (Docker)

Rooster draait ook als losse container, bijvoorbeeld op een Raspberry Pi naast
de facturen-app. Alles werkt hetzelfde. Alleen is er geen zijbalk van Home
Assistant: je opent de app in je browser op `http://<adres-van-de-pi>:8100/`
en logt in met een eigen wachtwoord.

Alle opdrachten typ je op de Pi, tenzij er staat dat het in Home Assistant moet.

## 1. Installeren

```sh
cd ~
git clone https://github.com/stsanders06/rooster-app.git
cd rooster-app
cp .env.example .env
mkdir -p data
docker compose up -d --build
docker compose ps
```

Bij `STATUS` hoort `Up ... (healthy)` te staan. Open daarna meteen de app en
kies een wachtwoord. Zolang je dat niet hebt gedaan, kan iedereen op je
netwerk er een kiezen.

Pas `docker-compose.yml` niet aan; zet alles in `.env` (poort, tijdzone,
`PUID`/`PGID`). Anders mislukt `git pull` bij het bijwerken. Docker zet zijn
regels vóór die van ufw, dus een firewallregel houdt de poort niet tegen.
Zet de poort nooit open in je router.

**Wachtwoord vergeten:** `rm ~/rooster-app/data/toegang.json`, open de app en
kies meteen een nieuw. Iedereen die ingelogd was, is dan uitgelogd.

## 2. Je gegevens uit Home Assistant meenemen

### 2a. In Home Assistant (app Terminal & SSH)

```sh
SLUG=$(ha addons --raw-json | jq -r '.data.addons[] | select(.name=="Rooster") | .slug')
echo $SLUG
ha addons stop $SLUG
ha backups new --addons $SLUG --name rooster-verhuizing
ls -t /backup | head -1
scp /backup/$(ls -t /backup | head -1) <gebruiker>@<adres-van-de-pi>:~/rooster-verhuizing.tar
```

Laat de add-on daarna uit staan en zet **Start bij opstarten** uit. Twee apps
naast elkaar zetten je diensten twee keer in de iCloud-agenda.

### 2b. Op de Pi

```sh
cd ~/rooster-app
docker compose stop
mkdir -p /tmp/rooster-verhuizing && cd /tmp/rooster-verhuizing
tar -xf ~/rooster-verhuizing.tar
tar -xzf *rooster_app.tar.gz
cp -a data/. ~/rooster-app/data/
cd ~/rooster-app
docker compose up -d
rm -r /tmp/rooster-verhuizing
```

In `data` horen daarna in elk geval `rooster.db` en `options.json` te staan.
Geeft `tar -xzf` de melding `not in gzip format`, dan is de back-up
versleuteld; maak hem opnieuw in de terminal zoals in stap 2a.

`options.json` komt mee uit Home Assistant. Daarin staan de opties van de
add-on (inlog voor MyManus, `sync_uren`, `verlof_opbouw_uren`,
`verlof_vanaf`). Op de Pi pas je die aan in dat bestand en start je daarna
opnieuw met `docker compose restart`. Wil je de MyManus-inlog liever in de
app beheren, haal gebruikersnaam en wachtwoord dan uit `options.json`.

## 3. Bijwerken

```sh
cd ~/rooster-app
docker compose stop
tar -czf ~/rooster-backup-$(date +%F).tar.gz data
git pull && docker compose up -d --build
docker image prune -f
```

## 4. Back-up

Alles staat in de map `data`.

```sh
cd ~/rooster-app
docker compose stop
tar -czf ~/rooster-backup-$(date +%F).tar.gz data
docker compose start
```
