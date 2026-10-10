# Rooster

MyManus-rooster in de zijbalk van Home Assistant: gewerkte dagen, uren tegenover
je contract, een geschat bruto en netto, en een agendafeed voor je iPhone.

De add-on leest alleen. Inloggen bij MyManus is de enige keer dat er iets
naar de server gaat; diensten wijzigen, verlof aanvragen of uren bevestigen
doet hij niet.

## Installatie

1. Ga naar **Instellingen → Add-ons → Add-on Store**.
2. Klik rechtsboven op de drie puntjes → **Repositories**.
3. Voeg toe: `https://github.com/stsanders06/rooster-app`
4. De add-on **Rooster** verschijnt in de store. Klik erop en kies **Installeren**.
   De eerste keer duurt dit een paar minuten, omdat het image lokaal gebouwd wordt.
5. Vul onder **Configuratie** je MyManus-gebruikersnaam en wachtwoord in, of laat
   ze leeg en vul ze straks in de app in. Zet **Start on boot** aan als je dat wilt.
6. Klik **Starten** en zet **Show in sidebar** aan.
7. Open **Rooster** in de zijbalk en tik op **Vernieuwen**.

Het dashboard op poort 8099 is bewust dicht. Wie daar rechtstreeks naartoe gaat,
ziet alleen de uitleg dat de app in de zijbalk hoort. De poort dient de agendafeed.

## Configuratie

| Optie | Standaard | Betekenis |
| --- | --- | --- |
| `gebruikersnaam` | leeg | MyManus-gebruikersnaam. Leeg = invullen in de app. |
| `wachtwoord` | leeg | MyManus-wachtwoord. Het veld is afgeschermd. |
| `sync_uren` | `4` | Uren tussen twee automatische keer ophalen. Minimum 1, maximum 168. |
| `log_level` | `info` | Hoeveel detail er in het add-onlog komt. |

Staan gebruikersnaam én wachtwoord in de add-on, dan gelden die. De
instellingenpagina kan ze dan niet overschrijven. Laat je ze hier leeg, dan
bewaart de app ze in `/data/geheim.json`. Dat bestand is niet versleuteld en
staat vanaf het aanmaken op modus 0600. Een backup van Home Assistant neemt
`/data` mee, dus ook dit wachtwoord. Het afgeschermde veld in de
add-onconfiguratie is de nettere plek.

Het wachtwoord van MyManus blijft een gewoon wachtwoord. De sessie die de app
daarmee krijgt is dezelfde als in de browser en verloopt na een tot veertien
dagen. Bij een verlopen sessie logt de app zelf opnieuw in.

## Wat er wordt opgehaald

Eens per paar uur, en als je op **Vernieuwen** tikt:

- het rooster van ongeveer twee maanden terug tot vijf weken vooruit
- de laatst afgesloten periode (uren, toeslag, plus/min)
- verlof en het verlofsaldo

Oudere weken die MyManus niet meer teruggeeft, blijven in `/data` staan.
Een week die wél opnieuw binnenkomt, vervangt die week, zodat een verschoven
dienst niet dubbel in de agenda belandt.

De winkel en het medewerkernummer komen uit MyManus na het inloggen. Die horen
niet in de configuratie.

## Het maandscherm

Elke maand is **gepland/geschat** zolang er nog geen afgesloten periode voor is,
en **definitief** zodra die er is. Bij een definitieve maand komen de uren en de
toeslag uit MyManus. Bij een geplande maand telt de app ze uit het rooster:
standaard 50% na 18:00 en op zondag. Die regels staan bij Instellingen en
stapelen niet — op een zondagavond geldt het hoogste percentage.

Het contract per maand is de weekuren × 52/12. Dertig uur per week is daarmee
130 uur, niet dertig keer het aantal dagen gedeeld door zeven. Verlofdagen
(maandag tot en met vrijdag) tellen mee als gewerkte uren in die plus/min:
een vijfde van de weekuren per vrije dag. Als MyManus een eigen plus/min
meestuurt, staat dat er los bij. Dat is hun saldo, niet automatisch hetzelfde
als jouw contracturen.

Bruto en netto zijn een schatting. De loonheffing op gewoon loon volgt de
schijven, de algemene heffingskorting en de arbeidskorting van het tabeljaar,
gedeeld door twaalf. Voor een jaar waarvoor de app nog geen tabel heeft,
gebruikt hij de laatste die hij kent en zegt het scherm "tabellen van" dat
jaar. De witte tabel van de Belastingdienst rondt net iets anders, reken op
hooguit een euro verschil rond een gewoon maandloon. Het netto heet daarom
overal een schatting.

### Werkmaand en uitbetaalmaand

Een periode kan in dezelfde maand betalen of een maand later. De app houdt die
twee uit elkaar.

De meegeleverde perioden, die je zelf aanpast:

- **Hulpkracht**, t/m 30 september 2026. Flex, vergeleken met 12 uur per week
  (het contract is 3 tot 12; zet het aantal dat jij wilt aanhouden). All-in:
  verlofuren worden uitbetaald, vakantiegeld elke maand. Uitbetaald een maand
  later.
- **Parttime verkoopmedewerker**, vanaf 1 oktober 2026. 30 uur per week, vast
  maandloon (130 uur × uurloon). Verlof wordt gewoon doorbetaald; uren boven
  het contract komen er los bij en minuren blijven een saldo. 8% vakantiegeld
  bouwt op en gaat mee met het salaris van mei. Uitbetaald in de maand zelf.

Het uurloon staat bewust leeg. Vul het in bij de hulpkracht; de parttime
periode neemt dat over tot je daar een eigen bedrag neerzet.

Gevolg, zonder dat oktober een uitzondering in de code is: in oktober komen
de september-uren (oud, achteraf) en de oktober-uren (nieuw, dezelfde maand)
in één uitbetaling. De loonheffing op dat gewone loon gaat over het hele
bedrag, niet over de twee maanden apart.

Het vakantiegeld in mei is geen gewoon maandloon. Daarop past de app het
percentage uit de tabel bijzondere beloningen van 2026 toe, bij het jaarloon
zonder die beloning (het gewone loon van die uitbetaling, keer twaalf).

### Hoe de bedragen zijn opgebouwd

Voor een all-in maand, in de volgorde van de strook:

- salaris = uren × uurloon, of bij vast maandloon de contracturen × uurloon
  plus de uren erboven
- toeslag = toeslaguren × uurloon × percentage
- uitbetaald verlof = uren × flexpercentage × uurloon, alleen bij all-in
- vakantiegeld = 8% over salaris plus dat verlof, niet over de toeslag
- pensioen = werknemersdeel over het brutoloon ná de eigen premie, boven een
  franchise die meeloopt met je uren (standaard de detailhandel-franchise van
  2026, € 18.680 per jaar, fulltime 38 uur)
- WGA, als je een percentage invult
- loonheffing over het gewone loon van de uitbetaling; vakantiegeld via de
  tabel bijzondere beloningen

Bij een definitieve maand komt de toeslag uit `compensationGained`: dat zijn
de toeslagminuten zelf. 300 minuten bij 50% is 5 uur toeslag, oftewel
10 bijzondere uren.

## Agenda op de iPhone

De feed staat op `/agenda/<token>.ics`. Het token is het wachtwoord: wie de
link heeft, ziet je diensten en verlof. In Instellingen maak je een nieuwe
link; de oude werkt dan niet meer.

Een dienst heet bijvoorbeeld `09:00-18:00 Bouwmarkt Voorbeeld`. Afdeling en
pauze staan in de omschrijving. Verlof is een hele dag. De afspraak houdt
dezelfde UID, zodat een nieuwe sync geen dubbele afspraak wordt.

De iPhone moet die link kunnen ophalen **zonder** in Home Assistant in te
loggen. De zijbalk-link werkt daar niet voor.

1. Zet bij de add-on de poort open (standaard 8099 op de host, dat mag je
   wijzigen).
2. Vul in Instellingen het adres waarop je telefoon de add-on bereikt. Op de
   kale poort is dat `http://`, bijvoorbeeld `http://192.168.1.20:8099`. Https
   krijg je alleen als je zelf een reverse proxy of tunnel voor die poort zet;
   de add-on levert geen certificaat. De hele link verschijnt dan op de pagina.
3. Op de iPhone: **Agenda → Agenda’s → Voeg agenda-abonnement toe**, en plak de link.

Alleen Nabu Casa aanzetten is niet genoeg. Dat maakt het Home Assistant-scherm
bereikbaar, niet de poort van een add-on. De telefoon heeft een adres nodig dat
rechtstreeks op de feed uitkomt: een poort die je op de router doorzet, een
tunnel, of een VPN. Thuis, of via een VPN, volstaat het interne adres. De
geheime link is de beveiliging; zet de poort niet open zonder die token, en
deel de link niet.

### Dezelfde feed in Home Assistant

Home Assistant leest de feed van binnenuit, daar is geen poort naar buiten voor nodig.

1. **Instellingen → Apparaten en diensten → Agenda toevoegen → iCal**
   (de integratie heet ook wel CalDAV/iCal, kies de variant die een ICS-adres vraagt).
2. Adres: `http://<ip-van-home-assistant>:8099/agenda/<token>.ics`

Het ip is dat van Home Assistant zelf, vanuit het netwerk waar Home Assistant
de add-on op kan aanspreken. Het token staat in de app onder Instellingen.

## Eerste gebruik

1. Start de add-on en open hem via de zijbalk.
2. Controleer bij Instellingen of het inloggen er staat, en tik op **Nu vernieuwen**.
3. Vul het uurloon van de hulpkracht in. De periode erna neemt het over tot je
   het vervangt.
4. Loop de twee contractperioden na: uren per week, all-in, vakantiegeld,
   achteraf betalen, pensioenpercentage en franchise, en de toeslagregels.
5. Plak de agendalink op je telefoon als je die buiten huis wilt.

Na een update: stop de add-on en start hem opnieuw. Alleen opslaan is niet
genoeg, anders blijft de vorige versie draaien.
