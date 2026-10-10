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
toeslag uit MyManus. Bij een geplande maand telt de app ze uit het rooster,
volgens de cao Doe-het-zelfbranche (artikel 8.2.1): 50% maandag tot en met
zaterdag van 0:00 tot 6:00, 50% maandag tot en met vrijdag van 21:00 tot
24:00, 50% van zaterdag 18:00 tot en met zondag, en 100% op een feestdag.
De feestdag vervangt de 50%. Feestdagen worden uitgerekend, inclusief
Pasen. Koningsdag schuift naar 26 april als 27 april een zondag is.
Bevrijdingsdag telt alleen in een lustrumjaar. Die regels staan bij
Instellingen.

Het contract per maand is de weekuren × 52/12. Dertig uur per week is daarmee
130 uur, niet dertig keer het aantal dagen gedeeld door zeven. Verlofdagen
(maandag tot en met vrijdag) tellen mee als gewerkte uren in die plus/min:
een vijfde van de weekuren per vrije dag. Als MyManus een eigen plus/min
meestuurt, staat dat er los bij. Dat is hun saldo, niet automatisch hetzelfde
als jouw contracturen.

Bruto en netto zijn een schatting. De loonheffing op gewoon loon is de
witte maandtabel van de Belastingdienst, mét loonheffingskorting, in
stappen van € 4,50. Voor een jaar waarvoor de app nog geen tabel heeft,
gebruikt hij de laatste die hij kent en zegt het scherm "tabellen van" dat
jaar. Het netto heet een schatting omdat het uurloon, de uren en de
premies een benadering van de strook zijn. De heffing zelf is de tabel.

### Wat een maand laat zien

Het scherm toont het loon van de uren die je in die maand hebt gewerkt.
Oktober laat alleen de oktoberuren zien, september alleen die van september.
De loonheffing is de witte maandtabel over dat maandloon, alsof die maand
op zichzelf staat. Twee maanden worden niet bij elkaar opgeteld.

De meegeleverde perioden, die je zelf aanpast:

- **Hulpkracht**, t/m 30 september 2026. Flex, vergeleken met 12 uur per week
  (het contract is 3 tot 12; zet het aantal dat jij wilt aanhouden). All-in:
  het uurloon plus 9,2308% verlofuren plus 8% vakantiegeld daarover. Dat
  vakantiegeld zit in het bruto en het netto van die maand. 9,2308% is
  24 dagen, 182,4 uur op een fulltimejaar van 1976 uur.
- **Parttime verkoopmedewerker**, vanaf 1 oktober 2026. 30 uur per week, vast
  maandloon (130 uur × uurloon). Verlof wordt gewoon doorbetaald; uren boven
  het contract komen er los bij en minuren blijven een saldo. 8% vakantiegeld
  bouwt op. Dat staat als reservering op het scherm en telt niet mee in het
  netto. Je ziet wat er nog openstaat tot de mei waarin het vrijkomt.

Het uurloon staat bewust leeg. Vul het in bij de hulpkracht; de parttime
periode neemt dat over tot je daar een eigen bedrag neerzet. Of zet bij
Instellingen een cao-loonschaal en een geboortedatum. De schaal stelt dan
het uurloon voor zolang het veld leeg is, en een leeftijdsstap gaat in in
de maand van de verjaardag. De geboortedatum blijft in de gegevensmap.

### Hoe de bedragen zijn opgebouwd

Voor een all-in maand, in de volgorde van de strook:

- salaris = uren × uurloon, of bij vast maandloon de contracturen × uurloon
  plus de uren erboven
- toeslag = toeslaguren × uurloon × percentage
- overwerk, als dat aan staat: boven 9 uur op een dag, of boven gemiddeld
  40 uur per week over 4 aaneengesloten weken. De eerste twee van die uren
  zijn 125% van het uurloon, de rest 150%. Het uur zelf zit al in het
  salaris, dus alleen de 25% of 50% komt erbij. Uren tussen het contract en
  die grens blijven op het gewone tarief. Een afgesloten maand heeft dit
  niet apart, omdat MyManus daar één toeslaggetal levert
- uitbetaald verlof = uren × flexpercentage × uurloon, alleen bij all-in
- vakantiegeld = 8% over salaris plus dat verlof, niet over de toeslag en
  niet over het overwerk. Uitbetaald vakantiegeld zit in de maand.
  Opgebouwd vakantiegeld is een reservering. De tabel bijzondere
  beloningen schat de loonheffing bij uitbetaling, op het jaarloon van die
  maand maal twaalf, en rondt af in het voordeel van de werknemer. Dat
  bedrag gaat niet van het netto af
- pensioen = werknemersdeel 6,1875% over het brutoloon ná de eigen premie.
  De grondslag is het sv-loon min de franchise, en minimaal nul. De
  franchise van € 18.680 per jaar gaat naar rato van de uren tegenover een
  fulltime maand van 38 × 52/12 uur. Fulltime is dat € 1.556,67 per maand.
  Het pensioengevend loon stopt bij € 79.409 per jaar
- WGA, als je een percentage invult
- loonheffing over het sv-loon van deze gewerkte maand, volgens de witte
  maandtabel. Opgebouwd vakantiegeld hoort daar niet bij

Bij een definitieve maand komt de toeslag uit `compensationGained`: dat zijn
de toeslagminuten zelf. 300 minuten bij 50% is 5 uur toeslag, oftewel
10 bijzondere uren.

## Bronnen

De standaardbedragen komen uit openbare stukken. Je kunt ze in Instellingen
aanpassen.

- [Cao Doe-het-zelfbranche, 1 juli 2026 tot en met 30 juni 2027](https://www.fnv.nl/getmedia/5ab70fbb-60c4-4009-b7a8-b45529f19094/1040-doe-het-zelfbranche-cao-01-07-2026-tm-30-06-2027-v11082026.pdf)
- [Pensioenfonds Detailhandel, premieoverzicht 2026](https://pensioenfondsdetailhandel.nl/content/Publicaties/Rekenvoorbeelden/Premieoverzicht-2026.pdf)
- [Belastingdienst, witte maandtabel 2026](https://download.belastingdienst.nl/belastingdienst/dl/rekenhulpen/loonheffing/2026/v01/pdf/wit_mnd_nl_std_20260101.pdf)
- [Belastingdienst, tabel bijzondere beloningen 2026](https://download.belastingdienst.nl/belastingdienst/dl/rekenhulpen/loonheffing/2026/v01/pdf/wit_bb_nl_std_20260101.pdf)

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
   pensioenpercentage en franchise, en de toeslagregels.
5. Plak de agendalink op je telefoon als je die buiten huis wilt.

Na een update: stop de add-on en start hem opnieuw. Alleen opslaan is niet
genoeg, anders blijft de vorige versie draaien.
