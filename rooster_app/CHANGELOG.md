# Changelog

## 1.4.0

- Oude Scriptable-afspraken opruimen is weg. Die lijst klopte in de praktijk
  niet. Afspraken van het oude script haal je zelf uit de agenda. Afspraken
  van deze app in een vorige agenda kun je nog wel eerst bekijken en daarna
  weghalen.
- De agendalink is weg. Er is geen losse link meer om je rooster op te
  abonneren, en de add-on zet geen poort meer open. Je diensten komen in de
  gedeelde iCloud-agenda. De herinnering stel je daar in.
- De WGA-premie werknemer gaat van het netto af, ná de loonheffing. Het is
  het sv-loon maal het percentage, standaard 0,808%, afgerond op centen.
  Je past het percentage per contractperiode aan bij Instellingen. Een
  periode die nog op 0 stond krijgt eenmalig 0,808%.
- Afspraken die je zelf uit de gedeelde agenda haalt, komen bij de
  volgende keer ophalen terug. De app gaat af op de agenda zoals die nu
  is. Een oude verwijzing naar een weggehaalde afspraak wordt geen fout.
- Verlof dat maar een deel van de dag is, komt in de agenda met een tijd,
  bijvoorbeeld `Vrij vanaf 18:00`. Een hele dag blijft `Vrij`, zonder tijd
  en zonder herinnering. In de notitie staan je eigen tekst, de memo en de
  soort. Een openstaande aanvraag krijgt `(aangevraagd)` ervoor. Een
  afgewezen aanvraag komt niet in de agenda. Een dienst op dezelfde dag
  blijft een eigen afspraak.
- Bij het contract op Instellingen staat het uurloon uit MyManus, als dat
  in het rooster zit, met de datum vanaf wanneer het geldt. **Overnemen**
  vult alleen het uurloon van die periode. Het veld blijft leeg tot je
  daar zelf op tikt.
- Een dienst telde sinds 1.3.0 soms twee keer mee. De sleutel veranderde,
  en het komende rooster gebruikte een ander id dan het weekrooster. De
  uren van zo'n maand lagen daardoor te hoog, en er verscheen overwerk dat
  er niet hoorde. Bij het starten gaan die dubbele rijen weg. In de
  gedeelde agenda verdwijnt alleen de extra afspraak van deze app.

## 1.3.0

- Diensten en verlof kunnen in een bestaande gedeelde iCloud-agenda gezet
  worden, na elke keer ophalen. Andere afspraken in die agenda blijven
  staan. Je kiest de agenda op naam, met een app-wachtwoord van Apple.
- Een dienst heet nu `17:00 - winkel`: de eindtijd en de winkelnaam. In de
  notitie staan winkelcode, afdeling (`03 - naam`), werktijd en pauze, en
  onderaan `[AUTO-ADDED]`. Twee uur van tevoren een herinnering; dat stel je
  in.
- Een verschoven diensttijd werkt de bestaande afspraak bij.
- iCloud ontkoppelen haalt het Apple-id en het app-wachtwoord weg. Die
  staan in de gegevensmap, en die map zit in een back-up van Home Assistant
  tot je ontkoppelt.
- Wissel je van agenda, dan kun je de afspraken van deze app in de vorige
  agenda eerst bekijken en daarna weghalen.

- Oudere afgesloten maanden worden ook opgehaald. Die bleven op
  gepland/geschat staan, met de uren van het rooster, omdat alleen de
  laatst afgesloten periode binnenkwam. Een maand die al definitief is,
  wordt niet elke keer opnieuw opgehaald.

## 1.2.0

- De standaardregels volgen de cao Doe-het-zelfbranche 2026-2027, het
  premieoverzicht van Pensioenfonds Detailhandel 2026 en de witte
  maandtabel van de Belastingdienst. Je kunt ze bij Instellingen nog
  aanpassen.
- Verlofopbouw bij all-in is 9,2308% per betaald uur. Vakantiegeld blijft
  8% en, als het wordt opgespaard, alleen een reservering op het scherm.
- Toeslag: 50% in de nacht tot 6:00, 50% maandag tot en met vrijdag vanaf
  21:00, 50% van zaterdag 18:00 tot en met zondag, en 100% op feestdagen.
  Een feestdag vervangt de 50%.
- Overwerk boven 9 uur op een dag of gemiddeld 40 uur per week staat aan.
  De eerste twee uur zijn 125%, daarna 150%. Uren tussen je contract en
  die grens blijven op het gewone uurloon. Zet het uit als je contract
  dat anders afspreekt.
- De loonheffing is de witte maandtabel van 2026, niet meer een
  jaarberekening gedeeld door twaalf. Opgespaard vakantiegeld noemt de
  tabel bijzondere beloningen, zonder dat bedrag van het netto af te halen.
- Bij Instellingen kun je een cao-loonschaal kiezen. Met een geboortedatum
  vult de app dan een leeg uurloon. Die datum blijft in de gegevens van de
  add-on. Een uurloon dat je zelf invult gaat voor.
- Onder Instellingen staan de bronnen van de bedragen.
- Op een smalle telefoon blijven de datumvelden in de kaart, met dezelfde
  hoogte als de andere velden. De afstanden tussen kop, veld, hulptekst,
  vinkje en knop zijn gelijk. Onder de balk van Home Assistant staat geen
  extra lege strook meer. Een leeg uurloon heeft een kort invoerveld; de
  uitleg staat eronder.
- In een tweekolomsrij staan de invoervelden op één lijn, ook als een
  label omslaat. Lange labels zijn korter, zoals Flexverlof (%).

## 1.1.0

- Een maand laat zien wat de uren van díe maand opleveren. Oktober toont
  alleen oktober, september alleen september. De geschatte loonheffing en
  het netto horen bij die maand.
- De melding over twee maanden in één uitbetaling is weg, net als de regels
  over in welke maand het loon op de rekening staat.
- Opgebouwd vakantiegeld blijft een reservering op het scherm. Het telt niet
  mee in het netto. Vakantiegeld dat elke maand wordt uitbetaald, zit wél in
  het loon van die maand.
- Bij de contractperioden kun je niet meer kiezen of het loon een maand
  later komt.

## 1.0.0

- Rooster uit MyManus, ongeveer twee maanden terug tot vijf weken vooruit,
  bewaard in de add-on zodat een oude maand blijft staan.
- Maandscherm met uren, toeslag, contract, geschat bruto en netto, en het
  verschil tussen de maand waarin je werkt en de maand waarin het loon komt.
- Twee meegeleverde contractperioden: hulpkracht t/m september 2026 (all-in,
  achteraf, uren × uurloon) en parttime vanaf oktober 2026 (vast maandloon
  van weekuren × 52/12, verlof telt mee als gewerkt, vakantiegeld loopt op
  tot mei). Oktober toont daardoor twee maanden in één uitbetaling. Het
  uurloon vul je zelf in.
- Vakantiegeld in mei wordt belast met de tabel bijzondere beloningen, niet
  met de maandtabel over het hele bedrag.
