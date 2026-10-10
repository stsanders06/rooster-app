"""Schrijf het rooster naar een bestaande iCloud-agenda via CalDAV.

Alleen afspraken met ons kenmerk worden aangeraakt. De rest van een
gedeelde gezinsagenda — van anderen, of van het oude Scriptable-script —
blijft staan, tenzij iemand het opruimen expliciet bevestigt na een voorbeeld.

De aanroepen zijn vast: principal, calendar-home, een rapport over het
venster, en PUT/DELETE met ETag. Daarom volstaat de standaardbibliotheek.
Een extra pakket met native bibliotheken past niet bij het Alpine-image.
"""
from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from agenda import ics_voor_icloud, kern_van_ics, zelfde_afspraak
from datums import bereik_rond

log = logging.getLogger("rooster")

BASIS = "https://caldav.icloud.com/"
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
_MAX_OPRUIMEN = 200


class IcloudFout(Exception):
    def __init__(self, bericht: str, status: int | None = None):
        super().__init__(bericht)
        self.status = status


def standaard_opener(methode: str, url: str, headers: dict, body: bytes | None, timeout: float):
    verzoek = urllib.request.Request(url, data=body, headers=headers, method=methode)
    try:
        with urllib.request.urlopen(verzoek, timeout=timeout) as antwoord:
            return antwoord.status, _koppen(antwoord.headers), antwoord.read()
    except urllib.error.HTTPError as fout:
        return fout.code, _koppen(fout.headers), fout.read()
    except urllib.error.URLError as fout:
        raise IcloudFout("De iCloud-agenda is niet bereikbaar. Probeer het later opnieuw.") from fout


def _koppen(headers) -> dict:
    if headers is None:
        return {}
    return {str(sleutel): str(waarde) for sleutel, waarde in headers.items()}


def _kop(koppen: dict, naam: str) -> str | None:
    for sleutel, waarde in koppen.items():
        if sleutel.lower() == naam.lower():
            return waarde
    return None


def _icloud_url(url: str) -> bool:
    stuk = urllib.parse.urlparse(url)
    host = (stuk.hostname or "").lower()
    return stuk.scheme == "https" and (host == "icloud.com" or host.endswith(".icloud.com"))


def _lokale_naam(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _tekst(element) -> str:
    return "".join(element.itertext()).strip()


def _kind(element, naam: str):
    for kind in element:
        if _lokale_naam(kind.tag) == naam:
            return kind
    return None


def _soorten(element) -> set[str]:
    return {_lokale_naam(kind.tag) for kind in element}


class IcloudClient:
    def __init__(self, email: str, wachtwoord: str, opener=None, timeout: float = 20):
        self._email = email
        self._wachtwoord = wachtwoord
        self._opener = opener or standaard_opener
        self._timeout = timeout

    def agenda_lijst(self) -> list[dict]:
        """Agendanamen, inclusief agenda's die met dit account gedeeld zijn."""
        principal = self._eigenschap(BASIS, "current-user-principal", diepte="0", caldav=False)
        if not principal:
            raise IcloudFout("Apple gaf geen account terug.")
        home = self._eigenschap(principal, "calendar-home-set", diepte="0", caldav=True)
        if not home:
            raise IcloudFout("Apple gaf geen agenda's terug.")
        antwoorden, eind = self._propfind(home, _AGENDA_VRAAG, diepte="1")
        return _agenda_namen(antwoorden, eind)

    def afspraken(self, agenda_url: str, van: date, tot: date) -> list[dict]:
        self._eis_icloud(agenda_url)
        start, einde = _bereik_utc(van, tot)
        status, _koppen_antwoord, ruw, eind = self._verzoek(
            "REPORT",
            agenda_url,
            self._koppen_met({
                "Depth": "1",
                "Content-Type": "application/xml; charset=utf-8",
            }),
            _rapport(start, einde),
        )
        self._eis_ok(status, (207, 200))
        # Relatieve hrefs horen bij de server die uiteindelijk antwoordde,
        # niet bij het adres van vóór een doorverwijzing.
        return _afspraken_uit(ruw, eind)

    def haal(self, href: str) -> dict | None:
        self._eis_icloud(href)
        status, koppen, ruw, _eind = self._verzoek("GET", href, self._koppen_met({}), None)
        if status == 404:
            return None
        self._eis_ok(status, (200,))
        return {"href": href, "etag": _kop(koppen, "ETag"), "ics": ruw.decode("utf-8", errors="replace")}

    def schrijf(self, href: str, ics: str, etag: str | None, kenmerk: str) -> None:
        """Nieuwe afspraak met If-None-Match, bestaande met If-Match.

        Een 412 betekent dat de afspraak intussen veranderde. We kijken dan
        één keer of hij nog van ons is. Van iemand anders overschrijven we niet.
        """
        self._eis_icloud(href)
        self._zet(href, ics, etag, kenmerk, opnieuw=True)

    def verwijder(self, href: str, etag: str | None, kenmerk: str) -> None:
        if not etag:
            raise IcloudFout("Een afspraak zonder ETag wordt niet verwijderd.")
        self._eis_icloud(href)
        self._wis(href, etag, kenmerk, opnieuw=True)

    def _zet(self, href: str, ics: str, etag: str | None, kenmerk: str, opnieuw: bool) -> None:
        extra = {"Content-Type": "text/calendar; charset=utf-8"}
        if etag:
            extra["If-Match"] = etag
        else:
            extra["If-None-Match"] = "*"
        status, _koppen_antwoord, _ruw, _eind = self._verzoek(
            "PUT", href, self._koppen_met(extra), ics.encode("utf-8")
        )
        if status in (200, 201, 204):
            return
        if status != 412 or not opnieuw:
            self._eis_ok(status, (200, 201, 204))
            return
        bestaand = self.haal(href)
        if bestaand is None:
            if etag:
                self._zet(href, ics, None, kenmerk, opnieuw=False)
                return
            raise IcloudFout("De afspraak kon niet worden gezet.", 412)
        if not van_ons(bestaand["ics"], kenmerk):
            raise IcloudFout("Er staat al een andere afspraak op dit adres. Hij blijft staan.", 412)
        self._zet(href, ics, bestaand.get("etag"), kenmerk, opnieuw=False)

    def _wis(self, href: str, etag: str, kenmerk: str, opnieuw: bool) -> None:
        status, _koppen_antwoord, _ruw, _eind = self._verzoek(
            "DELETE", href, self._koppen_met({"If-Match": etag}), None
        )
        if status in (200, 204, 404):
            return
        if status != 412 or not opnieuw:
            self._eis_ok(status, (200, 204, 404))
            return
        bestaand = self.haal(href)
        if bestaand is None:
            return
        if not van_ons(bestaand["ics"], kenmerk):
            raise IcloudFout("Die afspraak is niet van deze app. Hij blijft staan.", 412)
        if not bestaand.get("etag"):
            raise IcloudFout("De afspraak kon niet worden verwijderd.", 412)
        self._wis(href, bestaand["etag"], kenmerk, opnieuw=False)

    def _eigenschap(self, url: str, naam: str, diepte: str, caldav: bool) -> str | None:
        vraag = (_PROPFIND_CALDAV if caldav else _PROPFIND).format(naam=naam)
        antwoorden, eind = self._propfind(url, vraag, diepte)
        for antwoord in antwoorden:
            href = antwoord["props"].get(naam)
            if href:
                return urllib.parse.urljoin(eind, href)
        return None

    def _propfind(self, url: str, vraag: str, diepte: str) -> tuple[list[dict], str]:
        self._eis_icloud(url)
        status, _koppen_antwoord, ruw, eind = self._verzoek(
            "PROPFIND",
            url,
            self._koppen_met({
                "Depth": diepte,
                "Content-Type": "application/xml; charset=utf-8",
            }),
            vraag.encode("utf-8"),
        )
        self._eis_ok(status, (207, 200))
        return _multistatus(ruw), eind

    def _koppen_met(self, extra: dict) -> dict:
        import base64

        token = base64.b64encode(f"{self._email}:{self._wachtwoord}".encode("utf-8")).decode("ascii")
        koppen = {
            "Authorization": f"Basic {token}",
            "User-Agent": "Rooster-add-on",
        }
        koppen.update(extra)
        return koppen

    def _verzoek(self, methode: str, url: str, headers: dict, body: bytes | None, sprongen: int = 0):
        if sprongen > 5:
            raise IcloudFout("Apple stuurde te veel doorverwijzingen.")
        self._eis_icloud(url)
        status, koppen, ruw = self._opener(methode, url, headers, body, self._timeout)
        if status in (301, 302, 307, 308):
            doel = _kop(koppen, "Location")
            if not doel:
                raise IcloudFout("Apple stuurde een doorverwijzing zonder adres.", status)
            return self._verzoek(methode, urllib.parse.urljoin(url, doel), headers, body, sprongen + 1)
        if status == 401:
            raise IcloudFout(
                "Apple weigerde het e-mailadres of het app-wachtwoord.",
                401,
            )
        return status, koppen, ruw, url

    def _eis_icloud(self, url: str) -> None:
        if not _icloud_url(url):
            # Het app-wachtwoord gaat alleen naar Apple, ook niet via een redirect.
            raise IcloudFout("Die agenda staat niet bij iCloud.")

    def _eis_ok(self, status: int, verwacht: tuple[int, ...]) -> None:
        if status in verwacht:
            return
        if status == 401:
            raise IcloudFout(
                "Apple weigerde het e-mailadres of het app-wachtwoord.",
                401,
            )
        if status == 403:
            raise IcloudFout("Apple geeft geen toegang tot deze agenda.", 403)
        raise IcloudFout(f"De iCloud-agenda antwoordde met een fout ({status}).", status)


_PROPFIND = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop><d:{naam}/></d:prop>
</d:propfind>
"""

# calendar-home-set hoort bij CalDAV, niet bij DAV. Een DAV-naam levert niets op.
_PROPFIND_CALDAV = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><c:{naam}/></d:prop>
</d:propfind>
"""

_AGENDA_VRAAG = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:resourcetype/>
    <d:displayname/>
  </d:prop>
</d:propfind>
"""


def _rapport(start: str, einde: str) -> bytes:
    # time-range is exclusief aan het eind en hoort in UTC. Het venster zelf
    # is een kalenderdag in Amsterdam; de omzetting zit in de aanroep.
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:getetag/>
    <c:calendar-data/>
  </d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT">
        <c:time-range start="{start}" end="{einde}"/>
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>
"""
    return xml.encode("utf-8")


def _bereik_utc(van: date, tot: date) -> tuple[str, str]:
    start = datetime(van.year, van.month, van.day, tzinfo=AMSTERDAM).astimezone(timezone.utc)
    einde = datetime(tot.year, tot.month, tot.day, tzinfo=AMSTERDAM) + timedelta(days=1)
    einde = einde.astimezone(timezone.utc)
    return start.strftime("%Y%m%dT%H%M%SZ"), einde.strftime("%Y%m%dT%H%M%SZ")


def _parse(ruw: bytes):
    if not ruw:
        raise IcloudFout("Apple stuurde geen leesbaar antwoord.")
    try:
        return ElementTree.fromstring(ruw)
    except ElementTree.ParseError as fout:
        raise IcloudFout("Apple stuurde geen leesbaar antwoord.") from fout


def _multistatus(ruw: bytes) -> list[dict]:
    wortel = _parse(ruw)
    uit = []
    for antwoord in wortel.iter():
        if _lokale_naam(antwoord.tag) != "response":
            continue
        href_el = _kind(antwoord, "href")
        props: dict[str, str] = {}
        for propstat in antwoord:
            if _lokale_naam(propstat.tag) != "propstat":
                continue
            status_el = _kind(propstat, "status")
            if status_el is not None and "200" not in _tekst(status_el):
                continue
            prop = _kind(propstat, "prop")
            if prop is None:
                continue
            for veld in prop:
                naam = _lokale_naam(veld.tag)
                if naam == "resourcetype":
                    props["resourcetype"] = " ".join(sorted(_soorten(veld)))
                elif naam in ("current-user-principal", "calendar-home-set"):
                    genest = _kind(veld, "href")
                    if genest is not None:
                        props[naam] = _tekst(genest)
                else:
                    props[naam] = _tekst(veld)
        uit.append({
            "href": _tekst(href_el) if href_el is not None else "",
            "props": props,
        })
    return uit


def _agenda_namen(antwoorden: list[dict], home: str) -> list[dict]:
    gezien: dict[str, int] = {}
    uit = []
    for antwoord in antwoorden:
        soorten = set(antwoord["props"].get("resourcetype", "").split())
        if "calendar" not in soorten:
            continue
        if soorten & {"schedule-inbox", "schedule-outbox"}:
            continue
        url = urllib.parse.urljoin(home, antwoord["href"])
        if not _icloud_url(url):
            continue
        naam = antwoord["props"].get("displayname") or _laatste_stuk(url)
        gezien[naam] = gezien.get(naam, 0) + 1
        label = naam if gezien[naam] == 1 else f"{naam} ({gezien[naam]})"
        uit.append({"naam": naam, "label": label, "url": url})
    uit.sort(key=lambda agenda: agenda["label"].lower())
    return uit


def _laatste_stuk(url: str) -> str:
    pad = urllib.parse.urlparse(url).path.rstrip("/")
    return pad.rsplit("/", 1)[-1] or "Agenda"


def _afspraken_uit(ruw: bytes, agenda_url: str) -> list[dict]:
    uit = []
    for antwoord in _multistatus(ruw):
        ics = antwoord["props"].get("calendar-data") or ""
        if "BEGIN:VEVENT" not in ics and "BEGIN:VCALENDAR" not in ics:
            continue
        href = urllib.parse.urljoin(agenda_url, antwoord["href"])
        if not _icloud_url(href):
            continue
        uit.append({
            "href": href,
            "etag": antwoord["props"].get("getetag") or None,
            "ics": ics,
        })
    return uit


def van_ons(ics: str, kenmerk: str) -> bool:
    kern = kern_van_ics(ics)
    return (
        kern["uid"].startswith("rooster-app-")
        and kern["uid"].endswith(f"@{kenmerk}")
        and kern["kenmerk"] == kenmerk
    )


def marker_in(ics: str, marker: str) -> bool:
    if not marker:
        return False
    kern = kern_van_ics(ics)
    return marker in kern["omschrijving"] or marker in kern["url"]


def _datum_uit_veld(waarde: str) -> date | None:
    cijfers = "".join(teken for teken in waarde if teken.isdigit())
    if len(cijfers) < 8:
        return None
    try:
        return date(int(cijfers[0:4]), int(cijfers[4:6]), int(cijfers[6:8]))
    except ValueError:
        return None


def _periode_uit_kern(kern: dict) -> tuple[date, date] | None:
    start = _datum_uit_veld(kern.get("start") or "")
    einde_veld = kern.get("einde") or ""
    einde = _datum_uit_veld(einde_veld)
    if start is None or einde is None:
        return None
    cijfers = "".join(teken for teken in einde_veld if teken.isdigit())
    # Een hele dag heeft een exclusieve DTEND. Middernacht is hetzelfde:
    # de afspraak hoort niet meer bij die volgende dag.
    if len(cijfers) == 8 or einde_veld.endswith("T000000"):
        einde = einde - timedelta(days=1)
    if einde < start:
        einde = start
    return start, einde


def overlapt_venster(ics: str, van: date, tot: date) -> bool:
    periode = _periode_uit_kern(kern_van_ics(ics))
    if periode is None:
        return False
    begin, eind = periode
    return begin <= tot and eind >= van


def href_voor(agenda_url: str, uid: str) -> str:
    basis = agenda_url if agenda_url.endswith("/") else agenda_url + "/"
    return basis + urllib.parse.quote(uid, safe="") + ".ics"


def spiegel_naar_icloud(opslag, vandaag: date, client=None) -> dict:
    """Maak de gekozen agenda gelijk aan het rooster in het sync-venster.

    Uit staat: er gaat niets naar Apple. Een fout hier mag het MyManus-rooster
    niet ongedaan maken; de melding komt op Instellingen te staan.
    """
    inst = opslag.lees_icloud()
    if not inst["aan"]:
        return {"gedaan": False}
    if not inst["email"] or not inst["wachtwoord"]:
        return _mislukt(opslag, "Vul je Apple-id en een app-wachtwoord in.")
    if not inst["agenda_url"] or not inst["kenmerk"]:
        return _mislukt(opslag, "Kies eerst welke agenda je wilt gebruiken.")
    if client is None:
        client = IcloudClient(inst["email"], inst["wachtwoord"])
    van, tot = bereik_rond(vandaag)
    try:
        return _spiegel(opslag, client, inst, van, tot, inst["agenda_url"])
    except IcloudFout as fout:
        log.info("iCloud-agenda mislukt (%s)", fout.status or "netwerk")
        return _mislukt(opslag, str(fout))


def _mislukt(opslag, bericht: str) -> dict:
    opslag.zet_icloud_status(fout=bericht)
    return {"gedaan": False, "fout": bericht}


def _spiegel(opslag, client, inst: dict, van: date, tot: date, agenda_url: str) -> dict:
    gewenst = _gewenste_afspraken(opslag, inst["kenmerk"], agenda_url, van, tot)
    try:
        gevonden = client.afspraken(inst["agenda_url"], van, tot)
    except IcloudFout:
        raise
    van_deze_app = {}
    for afspraak in gevonden:
        if not van_ons(afspraak["ics"], inst["kenmerk"]):
            continue
        if not overlapt_venster(afspraak["ics"], van, tot):
            continue
        uid = kern_van_ics(afspraak["ics"])["uid"]
        van_deze_app[uid] = afspraak

    aangemaakt = bijgewerkt = verwijderd = 0
    fouten = []
    for uid, nieuw in gewenst.items():
        bestaand = van_deze_app.get(uid)
        try:
            if bestaand is None:
                client.schrijf(nieuw["href"], nieuw["ics"], None, inst["kenmerk"])
                aangemaakt += 1
            elif not zelfde_afspraak(nieuw["kern"], kern_van_ics(bestaand["ics"])):
                client.schrijf(bestaand["href"], nieuw["ics"], bestaand.get("etag"), inst["kenmerk"])
                bijgewerkt += 1
        except IcloudFout as fout:
            if fout.status == 401:
                raise
            fouten.append(str(fout))
    for uid, bestaand in van_deze_app.items():
        if uid in gewenst:
            continue
        try:
            client.verwijder(bestaand["href"], bestaand.get("etag"), inst["kenmerk"])
            verwijderd += 1
        except IcloudFout as fout:
            if fout.status == 401:
                raise
            fouten.append(str(fout))

    verslag = f"{aangemaakt} nieuw, {bijgewerkt} bijgewerkt, {verwijderd} verwijderd"
    if fouten:
        verslag += ". " + fouten[0]
    nu = datetime.now(AMSTERDAM).replace(microsecond=0).isoformat()
    opslag.zet_icloud_status(verslag=verslag, fout=fouten[0] if fouten else "", laatste=nu)
    log.info("iCloud-agenda: %s", verslag.split(".", 1)[0])
    return {
        "gedaan": True,
        "aangemaakt": aangemaakt,
        "bijgewerkt": bijgewerkt,
        "verwijderd": verwijderd,
        "fout": fouten[0] if fouten else "",
    }


def _gewenste_afspraken(opslag, kenmerk: str, agenda_url: str, van: date, tot: date) -> dict:
    uit = {}
    for dienst in opslag.alle_diensten():
        if not (van <= dienst["datum"] <= tot):
            continue
        uid, ics = ics_voor_icloud(dienst, None, kenmerk, alarm_uren=opslag.alarm_uren())
        uit[uid] = {"href": href_voor(agenda_url, uid), "ics": ics, "kern": kern_van_ics(ics)}
    for verlof in opslag.alle_verlof():
        if verlof["tot"] < van or verlof["van"] > tot:
            continue
        uid, ics = ics_voor_icloud(None, verlof, kenmerk, alarm_uren=opslag.alarm_uren())
        uit[uid] = {"href": href_voor(agenda_url, uid), "ics": ics, "kern": kern_van_ics(ics)}
    return uit


def voorbeeld_oude_afspraken(opslag, vandaag: date | None = None, client=None) -> dict:
    """Dry-run. Er wordt niets verwijderd.

    Alleen afspraken in het sync-venster waarvan de notitie of de link de
    ingestelde tekst bevat. Afspraken van deze add-on horen daar niet bij.
    """
    inst = opslag.lees_icloud()
    if not inst["opruimen"]:
        raise IcloudFout("Zet opruimen eerst aan en sla op. Er is nog niets verwijderd.")
    marker = inst["marker"].strip()
    if not marker:
        raise IcloudFout("Vul de tekst in die in de oude afspraak staat.")
    if not inst["email"] or not inst["wachtwoord"]:
        raise IcloudFout("Vul eerst het e-mailadres en het app-wachtwoord in.")
    if not inst["agenda_url"]:
        raise IcloudFout("Kies eerst welke agenda je wilt gebruiken.")
    if client is None:
        client = IcloudClient(inst["email"], inst["wachtwoord"])
    van, tot = bereik_rond(vandaag or date.today())
    gevonden = client.afspraken(inst["agenda_url"], van, tot)
    regels = []
    for afspraak in gevonden:
        if van_ons(afspraak["ics"], inst["kenmerk"]):
            continue
        if not marker_in(afspraak["ics"], marker):
            continue
        if not overlapt_venster(afspraak["ics"], van, tot):
            continue
        kern = kern_van_ics(afspraak["ics"])
        periode = _periode_uit_kern(kern)
        wanneer = ""
        if periode:
            begin, eind = periode
            wanneer = begin.isoformat() if begin == eind else f"{begin.isoformat()} – {eind.isoformat()}"
        regels.append({
            "href": afspraak["href"],
            "titel": kern["samenvatting"] or "Afspraak",
            "wanneer": wanneer,
        })
    if len(regels) > _MAX_OPRUIMEN:
        raise IcloudFout(
            f"Er zijn meer dan {_MAX_OPRUIMEN} afspraken met die tekst. "
            "Maak de tekst specifieker. Er is niets verwijderd."
        )
    import secrets

    token = secrets.token_urlsafe(16)
    opslag.zet_icloud_voorbeeld({
        "token": token,
        "marker": marker,
        "agenda_url": inst["agenda_url"],
        "afspraken": regels,
    })
    return {"token": token, "afspraken": regels}


def verwijder_voorbeeld(opslag, token: str, client=None) -> dict:
    """Verwijder alleen wat in het voorbeeld stond, en alleen als het nog klopt."""
    import secrets

    bewaard = opslag.lees_icloud_voorbeeld()
    bewaard_token = str((bewaard or {}).get("token") or "")
    if (
        not bewaard
        or not token
        or len(token) != len(bewaard_token)
        or not secrets.compare_digest(bewaard_token, token)
    ):
        raise IcloudFout("Bekijk eerst het voorbeeld. Er is niets verwijderd.")
    inst = opslag.lees_icloud()
    if not inst["opruimen"] or inst["marker"].strip() != bewaard.get("marker"):
        raise IcloudFout("De tekst is veranderd. Bekijk het voorbeeld opnieuw.")
    if inst["agenda_url"] != bewaard.get("agenda_url"):
        raise IcloudFout("De agenda is veranderd. Bekijk het voorbeeld opnieuw.")
    if client is None:
        client = IcloudClient(inst["email"], inst["wachtwoord"])
    verwijderd = overgeslagen = 0
    for regel in bewaard.get("afspraken") or []:
        href = str(regel.get("href") or "")
        if not href:
            continue
        try:
            bestaand = client.haal(href)
            if bestaand is None:
                overgeslagen += 1
                continue
            if van_ons(bestaand["ics"], inst["kenmerk"]) or not marker_in(bestaand["ics"], inst["marker"].strip()):
                overgeslagen += 1
                continue
            client.verwijder(href, bestaand.get("etag"), inst["kenmerk"])
            verwijderd += 1
        except IcloudFout as fout:
            if fout.status == 401:
                raise
            overgeslagen += 1
    opslag.zet_icloud_voorbeeld(None)
    return {"verwijderd": verwijderd, "overgeslagen": overgeslagen}
