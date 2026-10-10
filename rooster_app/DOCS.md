# Rooster

MyManus-rooster in de zijbalk van Home Assistant: gewerkte dagen, uren tegenover
je contract, een geschat bruto en netto, en je diensten in een gedeelde
iCloud-agenda.

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

Het rooster open je alleen via de zijbalk. De add-on zet geen poort open.

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
- afgesloten periodes van dit jaar en vorig jaar (uren, toeslag, plus/min).
  Een periode die al is opgeslagen blijft staan en wordt niet opnieuw
  opgehaald; de nieuwste wel, voor het geval die net is afgesloten.
- verlof en het verlofsaldo, inclusief aanvragen. Een afgewezen
  aanvraag komt niet mee. Een aanvraag die nog openstaat wel, met
  de aanduiding dat hij nog niet is goedgekeurd.

Staat de gedeelde iCloud-agenda aan, dan schrijft de add-on daarna de
diensten en het verlof van datzelfde venster naar die agenda.

Oudere weken die MyManus niet meer teruggeeft, blijven in `/data` staan.
Een week die wél opnieuw binnenkomt, vervangt die hele week, ongeacht de
oude sleutel. Dezelfde dag met dezelfde begin- en eindtijd telt één keer,
ook als het weekrooster en de komende diensten een ander id gebruiken.
Een bestaande database wordt daar bij het starten op opgeschoond, zodat
een dienst die sinds 1.3.0 dubbel stond niet meer meetelt en de extra
afspraak uit de gedeelde agenda gaat. Afspraken van anderen blijven staan.

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
een vijfde van de weekuren per vrije dag. Verlof dat maar een deel van
de dag is, telt daar niet als hele vrije dag. Als MyManus een eigen plus/min
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
Staat er een uurloon in het rooster van MyManus, dan zie je dat bij het
contract als voorstel, met de datum vanaf wanneer het geldt. **Overnemen**
zet het in het uurloon van die periode. Van zichzelf blijft het veld leeg.

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
- loonheffing over het sv-loon van deze gewerkte maand, volgens de witte
  maandtabel. Opgebouwd vakantiegeld hoort daar niet bij. Op de strook
  heet dat loon het loon voor de loonheffing
- WGA-premie = sv-loon × het percentage, afgerond op centen. Dat is
  dezelfde grondslag als de loonheffing. Standaard 0,808%. De werkgever
  verhaalt de premie voor het WGA-hiaat op de werknemer, dus het bedrag
  gaat ná de loonheffing van het netto af. Het percentage stel je per
  contractperiode in, bij Instellingen onder **WGA-premie werknemer (%)**,
  zodat een ander jaar een ander tarief kan hebben. Bij 0% blijft de regel
  van het scherm af. Een periode die nog op de oude standaard 0 stond,
  krijgt eenmalig 0,808%

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

## Gedeelde iCloud-agenda

De add-on zet je diensten in een agenda die je al hebt, ook als je die met
je gezin deelt.

De add-on wijzigt alleen afspraken die hij zelf heeft gezet. Afspraken van
anderen blijven staan. Afspraken van een ouder script ook: die haal je zelf
weg in de agenda-app.

1. Ga op je iPhone of computer naar [account.apple.com](https://account.apple.com)
   en log in.
2. Open **Inloggen en beveiliging** en kies **App-specifieke wachtwoorden**.
   Maak een wachtwoord, bijvoorbeeld met de naam Rooster. Apple laat het
   één keer zien. Het gewone wachtwoord van je Apple-id werkt hier niet.
3. In de add-on, bij Instellingen: vul het e-mailadres van je Apple-id en dat
   app-wachtwoord in. Zet **Diensten naar deze agenda schrijven** aan en sla op.
4. Tik op **Agenda's ophalen** en kies de gedeelde agenda op naam.
5. Tik op **Nu vernieuwen**. De diensten van ongeveer twee maanden terug tot
   vijf weken vooruit komen in die agenda. Haal je die afspraken daarna
   zelf weg, dan zet de volgende keer ophalen ze terug. De app kijkt daarvoor
   naar wat er nú in de agenda staat, niet naar een eerdere lijst. Een dienst heet bijvoorbeeld
   `17:00 - Bouwmarkt Voorbeeld`: de eindtijd en de winkelnaam. In de notitie
   staan de winkel met winkelcode, de afdeling als `07 - Verkoop`, de
   gewerkte tijd (`6u15m`) en de pauze (`0u45m`). Onderaan staat
   `[AUTO-ADDED]`. Een hele vrije dag heet `Vrij` en heeft geen tijd en geen
   herinnering. Verlof dat om een kloktijd begint of eindigt, bijvoorbeeld
   vrij vanaf 18:00, is een afspraak met die tijd. In de notitie staan je
   eigen tekst, de memo en de soort, en onderaan `[AUTO-ADDED]`. Een dienst
   op dezelfde dag blijft een eigen afspraak. Een aanvraag die nog openstaat
   krijgt `(aangevraagd)` voor de titel. Een afgewezen aanvraag komt niet
   in de agenda.
6. Heb je nog een automatisering die dezelfde diensten in de agenda zet, zet
   die dan uit. Anders komen ze er dubbel in. Oude afspraken van dat script
   laat deze add-on staan.

Bij de iCloud-agenda stel je in hoeveel uur van tevoren de herinnering gaat.
Standaard twee uur. 0 zet hem uit.

Het app-wachtwoord staat in `/data/icloud.json` in de gegevensmap van de
add-on, niet in deze repository, en het bestand is alleen voor de add-on
leesbaar. Het komt niet in het log. Een back-up van Home Assistant neemt
`/data` mee, dus ook dit wachtwoord, tot je op **iCloud ontkoppelen** tikt.
Dat haalt het Apple-id en het app-wachtwoord weg. Het kenmerk waarmee de
app zijn eigen afspraken herkent, blijft staan, zodat een volgende keer
geen tweede reeks ontstaat.

Een dienst die uit het rooster verdwijnt, verdwijnt ook uit de agenda, maar
alleen binnen die periode en alleen als de afspraak van deze add-on is.
Buiten die periode laat de app bestaande afspraken staan. Schuift alleen
de tijd, dan wordt dezelfde afspraak bijgewerkt.

Kies je een andere agenda, dan biedt de app aan om de afspraken van deze
app in de vorige agenda weg te halen. Eerst een lijst, daarna bevestigen.
Afspraken van anderen blijven staan. Per keer hooguit 200; het scherm noemt
het totaal als het er meer zijn.

## Eerste gebruik

1. Start de add-on en open hem via de zijbalk.
2. Controleer bij Instellingen of het inloggen er staat, en tik op **Nu vernieuwen**.
3. Vul het uurloon van de hulpkracht in. De periode erna neemt het over tot je
   het vervangt.
4. Loop de twee contractperioden na: uren per week, all-in, vakantiegeld,
   pensioenpercentage en franchise, en de toeslagregels.
5. Zet bij Instellingen de gedeelde iCloud-agenda aan als de diensten in een
   agenda moeten die je al hebt.

Na een update: stop de add-on en start hem opnieuw. Alleen opslaan is niet
genoeg, anders blijft de vorige versie draaien.
