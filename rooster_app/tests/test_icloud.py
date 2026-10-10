"""iCloud-agenda tegen een nagebootste CalDAV-server.

Geen echte Apple-account, geen echt app-wachtwoord, geen echte namen.
"""
import os
from datetime import date

import pytest

import opslag
from agenda import ics_voor_icloud, kern_van_ics, maak_ics, uid_dienst, uid_voor_icloud
from conftest import INGRESS, csrf_uit
from icloud import IcloudClient, IcloudFout, spiegel_naar_icloud, verwijder_voorbeeld, voorbeeld_oude_afspraken
from manus import ManusFout

EMAIL = "voorbeeld@icloud.com"
WACHTWOORD = "abcd-efgh-ijkl-mnop"
AGENDA = "https://p01-caldav.icloud.com/123/calendars/gezin/"
MARKER = "scriptable-rooster"
VANDAAG = date(2026, 10, 10)


def _dienst(**wijzigingen):
    basis = {
        "datum": date(2026, 10, 10),
        "start_minuten": 9 * 60,
        "eind_minuten": 18 * 60,
        "pauze_minuten": 45,
        "totaal_minuten": 495,
        "winkel": "Bouwmarkt Voorbeeld",
        "winkel_code": "BV01",
        "afdeling": "Verkoop",
        "afdeling_code": "07",
        "afdeling_id": 3,
        "pauzes": [],
        "uniek": uid_dienst(date(2026, 10, 10), 9 * 60, 18 * 60, 3),
    }
    basis.update(wijzigingen)
    return basis


def _verlof():
    return {
        "van": date(2026, 11, 4),
        "tot": date(2026, 11, 5),
        "code": "V",
        "omschrijving": "Vakantie",
        "uniek": "verlof-2026-11-04-2026-11-05-v@rooster-app",
    }


def _zet_icloud(**wijzigingen):
    gegevens = {
        "email": EMAIL,
        "wachtwoord": WACHTWOORD,
        "aan": True,
        "agenda_url": AGENDA,
        "agenda_naam": "Gezin",
        "opruimen": False,
        "marker": "",
    }
    gegevens.update(wijzigingen)
    opslag.schrijf_icloud(gegevens)
    return opslag.lees_icloud()


class NepAgenda:
    def __init__(self, extra=None):
        self.extra = list(extra or [])
        self.opgeslagen = {}
        self.geschreven = []
        self.verwijderd = []
        self.teller = 0

    def afspraken(self, agenda_url, van, tot):
        eigen = [
            {"href": href, "etag": waarde["etag"], "ics": waarde["ics"]}
            for href, waarde in self.opgeslagen.items()
        ]
        return eigen + list(self.extra)

    def schrijf(self, href, ics, etag, kenmerk):
        self.geschreven.append((href, ics, etag, kenmerk))
        self.teller += 1
        self.opgeslagen[href] = {"etag": f'"e{self.teller}"', "ics": ics}

    def verwijder(self, href, etag, kenmerk):
        self.verwijderd.append((href, etag, kenmerk))
        self.opgeslagen.pop(href, None)
        self.extra = [afspraak for afspraak in self.extra if afspraak["href"] != href]

    def haal(self, href):
        if href in self.opgeslagen:
            waarde = self.opgeslagen[href]
            return {"href": href, "etag": waarde["etag"], "ics": waarde["ics"]}
        for afspraak in self.extra:
            if afspraak["href"] == href:
                return afspraak
        return None


def _ics_scriptable(wanneer="20261012T090000", einde="20261012T170000", marker=MARKER, uid="scriptable-1@icloud.com"):
    return "\r\n".join([
        "BEGIN:VCALENDAR",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTART;TZID=Europe/Amsterdam:{wanneer}",
        f"DTEND;TZID=Europe/Amsterdam:{einde}",
        "SUMMARY:Oude dienst",
        f"DESCRIPTION:{marker}",
        "END:VEVENT",
        "END:VCALENDAR",
    ])


def test_feed_houdt_zijn_eigen_uid():
    dienst = _dienst()
    assert uid_dienst(date(2026, 10, 10), 9 * 60, 18 * 60, 3) in maak_ics([dienst], [])
    assert "X-ROOSTER-APP" not in maak_ics([dienst], [])


def test_uit_stuurt_niets():
    _zet_icloud(aan=False)
    nep = NepAgenda()
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert verslag["gedaan"] is False
    assert nep.geschreven == []
    assert nep.verwijderd == []


def test_spiegel_is_een_keer_genoeg_en_laat_anderen_staan():
    inst = _zet_icloud()
    oud = ics_voor_icloud(_dienst(datum=date(2026, 7, 31), uniek="dienst-2026-07-31-540-1080-3@rooster-app"), None, inst["kenmerk"])
    buiten = {
        "href": "https://p01-caldav.icloud.com/123/calendars/gezin/buiten.ics",
        "etag": '"oud"',
        "ics": oud[1],
    }
    vreemd = {
        "href": "https://p01-caldav.icloud.com/123/calendars/gezin/familie.ics",
        "etag": '"fam"',
        "ics": _ics_scriptable(marker="verjaardag van oma"),
    }
    verdwenen_uid, verdwenen_ics = ics_voor_icloud(
        _dienst(datum=date(2026, 10, 11), uniek="dienst-2026-10-11-540-1080-3@rooster-app"),
        None,
        inst["kenmerk"],
    )
    verdwenen = {
        "href": "https://p01-caldav.icloud.com/123/calendars/gezin/weg.ics",
        "etag": '"weg"',
        "ics": verdwenen_ics,
    }
    opslag.bewaar_diensten([_dienst()])
    opslag.vervang_verlof_van_jaren([2026], [_verlof()])
    nep = NepAgenda(extra=[buiten, vreemd, verdwenen])
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert verslag["gedaan"] is True
    assert verslag["aangemaakt"] == 2
    assert verslag["verwijderd"] == 1
    assert verslag["verwijderd"] == 1
    assert nep.verwijderd[0][0] == verdwenen["href"]
    assert all(href != vreemd["href"] for href, _etag, _kenmerk in nep.verwijderd)
    assert all(href != buiten["href"] for href, _etag, _kenmerk in nep.verwijderd)
    lichamen = [ics for _href, ics, etag, _kenmerk in nep.geschreven]
    assert all(etag is None for _href, _ics, etag, _kenmerk in nep.geschreven)
    kernen = [kern_van_ics(ics) for ics in lichamen]
    assert any(kern["samenvatting"] == "18:00 - Bouwmarkt Voorbeeld" for kern in kernen)
    assert any("Afdeling: 07 - Verkoop" in kern["omschrijving"] for kern in kernen)
    assert any("Werktijd: 8u15m" in kern["omschrijving"] for kern in kernen)
    assert any("Pauze: 0u45m" in kern["omschrijving"] for kern in kernen)
    assert any(kern["omschrijving"].endswith("[AUTO-ADDED]") for kern in kernen)
    assert any(kern["alarm"] == "-PT2H" for kern in kernen)
    assert all("LOCATION" not in ics and "\nURL:" not in ics for ics in lichamen)
    assert any("DTSTART;TZID=Europe/Amsterdam:20261010T090000" in ics for ics in lichamen)
    assert any(f"X-ROOSTER-APP:{inst['kenmerk']}" in ics for ics in lichamen)
    assert any("DTSTART;VALUE=DATE:20261104" in ics for ics in lichamen)
    assert any("DTEND;VALUE=DATE:20261106" in ics for ics in lichamen)
    assert all(uid_voor_icloud("x", inst["kenmerk"]).split("@", 1)[1] == inst["kenmerk"] for _h, ics, _e, _k in nep.geschreven)
    assert opslag.lees_icloud_status()["verslag"].startswith("2 nieuw")

    nep.geschreven.clear()
    nep.verwijderd.clear()
    opnieuw = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert opnieuw["aangemaakt"] == 0
    assert opnieuw["bijgewerkt"] == 0
    assert opnieuw["verwijderd"] == 0
    assert nep.geschreven == []

    opgeslagen = opslag.alle_diensten()
    gewijzigd = dict(opgeslagen[0])
    gewijzigd["winkel"] = "Bouwmarkt Andere"
    opslag.vervang_week(date(2026, 10, 10), date(2026, 10, 10), [gewijzigd])
    bijgewerkt = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert bijgewerkt["bijgewerkt"] == 1
    assert bijgewerkt["aangemaakt"] == 0
    assert nep.geschreven[-1][2].startswith('"e')
    assert "Bouwmarkt Andere" in nep.geschreven[-1][1]


def test_verdwenen_dienst_in_het_venster_gaat_weg():
    inst = _zet_icloud()
    opslag.bewaar_diensten([_dienst()])
    nep = NepAgenda()
    spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    opslag.vervang_week(date(2026, 10, 10), date(2026, 10, 10), [])
    nep.verwijderd.clear()
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert verslag["verwijderd"] == 1
    assert nep.verwijderd[0][2] == inst["kenmerk"]


def test_wachtwoord_blijft_uit_de_fout_en_het_bestand_is_afgeschermd():
    class Opener:
        def __init__(self):
            self.aanroepen = []

        def __call__(self, methode, url, headers, body, timeout):
            self.aanroepen.append(url)
            return 401, {}, f"echo {WACHTWOORD}".encode()

    opener = Opener()
    client = IcloudClient(EMAIL, WACHTWOORD, opener=opener)
    with pytest.raises(IcloudFout) as gevonden:
        client.agenda_lijst()
    assert gevonden.value.status == 401
    assert "weigerde" in str(gevonden.value)
    assert WACHTWOORD not in str(gevonden.value)
    assert opener.aanroepen == ["https://caldav.icloud.com/"]

    oud = os.umask(0)
    try:
        _zet_icloud()
        modus = os.stat(opslag.ICLOUD_PATH).st_mode & 0o777
    finally:
        os.umask(oud)
    assert modus == 0o600
    eerste = opslag.lees_icloud()["kenmerk"]
    opslag.schrijf_icloud({"email": "ander@icloud.com", "wachtwoord": None})
    opnieuw = opslag.lees_icloud()
    assert opnieuw["kenmerk"] == eerste
    assert opnieuw["wachtwoord"] == WACHTWOORD
    assert opnieuw["agenda_url"] == ""


def test_doorverwijzing_blijft_bij_icloud_en_leest_gedeelde_agendas():
    class Opener:
        def __init__(self):
            self.urls = []

        def __call__(self, methode, url, headers, body, timeout):
            self.urls.append(url)
            if url == "https://caldav.icloud.com/":
                return 301, {"Location": "https://p01-caldav.icloud.com/"}, b""
            if url == "https://p01-caldav.icloud.com/":
                return 207, {}, b"""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/</d:href>
    <d:propstat>
      <d:prop>
        <d:current-user-principal><d:href>/123/principal/</d:href></d:current-user-principal>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>"""
            if url.endswith("/principal/"):
                return 207, {}, b"""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>/123/principal/</d:href>
    <d:propstat>
      <d:prop>
        <c:calendar-home-set><d:href>/123/calendars/</d:href></c:calendar-home-set>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>"""
            if url.endswith("/calendars/"):
                assert "If-Match" not in headers
                return 207, {}, """<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>/123/calendars/</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype><d:collection/></d:resourcetype>
        <d:displayname>home</d:displayname>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>/123/calendars/gezin/</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
        <d:displayname>Gezin</d:displayname>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>/123/calendars/inbox/</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype><c:schedule-inbox/></d:resourcetype>
        <d:displayname>In</d:displayname>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>""".encode()
            return 404, {}, b""

    opener = Opener()
    lijst = IcloudClient(EMAIL, WACHTWOORD, opener=opener).agenda_lijst()
    assert [agenda["naam"] for agenda in lijst] == ["Gezin"]
    assert lijst[0]["url"] == "https://p01-caldav.icloud.com/123/calendars/gezin/"
    assert opener.urls[0] == "https://caldav.icloud.com/"
    assert all(url.startswith("https://") and "icloud.com" in url for url in opener.urls)


def test_doorverwijzing_naar_een_andere_site_stuurt_het_wachtwoord_niet():
    class Opener:
        def __init__(self):
            self.urls = []

        def __call__(self, methode, url, headers, body, timeout):
            self.urls.append(url)
            return 301, {"Location": "https://evil.example/stel"}, b""

    opener = Opener()
    with pytest.raises(IcloudFout) as gevonden:
        IcloudClient(EMAIL, WACHTWOORD, opener=opener).agenda_lijst()
    assert "niet bij iCloud" in str(gevonden.value)
    assert opener.urls == ["https://caldav.icloud.com/"]
    assert WACHTWOORD not in str(gevonden.value)


def test_put_gebruikt_if_match_en_raakt_een_vreemde_afspraak_niet():
    class Opener:
        def __init__(self):
            self.aanroepen = []

        def __call__(self, methode, url, headers, body, timeout):
            self.aanroepen.append((methode, headers.get("If-Match"), headers.get("If-None-Match")))
            if methode == "PUT" and headers.get("If-None-Match") == "*":
                return 412, {}, b""
            if methode == "GET":
                return 200, {"ETag": '"van-een-ander"'}, b"""BEGIN:VCALENDAR
BEGIN:VEVENT
UID:van-oma@icloud.com
SUMMARY:Afspraak
DTSTART;TZID=Europe/Amsterdam:20261010T100000
DTEND;TZID=Europe/Amsterdam:20261010T110000
END:VEVENT
END:VCALENDAR
"""
            return 500, {}, b""

    opener = Opener()
    client = IcloudClient(EMAIL, WACHTWOORD, opener=opener)
    href = "https://p01-caldav.icloud.com/123/calendars/gezin/nieuw.ics"
    with pytest.raises(IcloudFout) as gevonden:
        client.schrijf(href, "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", None, "kenmerk")
    assert "blijft staan" in str(gevonden.value)
    assert opener.aanroepen[0][2] == "*"
    assert opener.aanroepen[0][1] is None


def test_voorbeeld_zonder_agenda_verwijdert_niets():
    _zet_icloud(opruimen=True, marker=MARKER, agenda_url="", agenda_naam="")
    nep = NepAgenda()
    with pytest.raises(IcloudFout) as gevonden:
        voorbeeld_oude_afspraken(opslag, VANDAAG, client=nep)
    assert "agenda" in str(gevonden.value)
    assert nep.verwijderd == []
    assert opslag.lees_icloud_voorbeeld() is None


def test_voorbeeld_verwijdert_pas_na_bevestiging():
    # Onze afspraak heeft dezelfde markering in de notitie. Die mag niet
    # in het voorbeeld, anders ruimt de knop het rooster van de add-on op.
    inst = _zet_icloud(opruimen=True, marker="[AUTO-ADDED]")
    _uid, van_ons_ics = ics_voor_icloud(_dienst(), None, inst["kenmerk"])
    assert "[AUTO-ADDED]" in van_ons_ics
    nep = NepAgenda(extra=[
        {
            "href": "https://p01-caldav.icloud.com/123/calendars/gezin/scriptable.ics",
            "etag": '"s"',
            "ics": _ics_scriptable(marker="[AUTO-ADDED]"),
        },
        {
            "href": "https://p01-caldav.icloud.com/123/calendars/gezin/ons.ics",
            "etag": '"o"',
            "ics": van_ons_ics,
        },
        {
            "href": "https://p01-caldav.icloud.com/123/calendars/gezin/oud.ics",
            "etag": '"juli"',
            "ics": _ics_scriptable(wanneer="20260701T090000", einde="20260701T170000"),
        },
        {
            "href": "https://p01-caldav.icloud.com/123/calendars/gezin/ander.ics",
            "etag": '"a"',
            "ics": _ics_scriptable(marker="iets anders", uid="ander@icloud.com"),
        },
    ])
    with pytest.raises(IcloudFout):
        verwijder_voorbeeld(opslag, "geen-voorbeeld", client=nep)
    assert nep.verwijderd == []

    voorbeeld = voorbeeld_oude_afspraken(opslag, VANDAAG, client=nep)
    assert [regel["titel"] for regel in voorbeeld["afspraken"]] == ["Oude dienst"]
    assert nep.verwijderd == []

    verslag = verwijder_voorbeeld(opslag, voorbeeld["token"], client=nep)
    assert verslag["verwijderd"] == 1
    assert nep.verwijderd[0][0].endswith("scriptable.ics")
    assert opslag.lees_icloud_voorbeeld() is None


def test_instellingen_bewaart_het_wachtwoord_zonder_het_te_tonen(client, monkeypatch):
    import main

    pagina = client.get("/instellingen", headers=INGRESS)
    html = pagina.get_data(as_text=True)
    assert "Gedeelde iCloud-agenda" in html
    assert "account.apple.com" in html
    assert "Oude Scriptable-afspraken" in html
    assert 'value="[AUTO-ADDED]"' in html
    assert 'name="alarm_uren" type="number" min="0" max="48" value="2"' in html
    assert "Deze afspraken verwijderen" not in html
    token = csrf_uit(html)
    antwoord = client.post(
        "/instellingen/icloud",
        data={
            "csrf_token": token,
            "email": EMAIL,
            "wachtwoord": WACHTWOORD,
            "aan": "ja",
        },
        headers=INGRESS,
        follow_redirects=True,
    )
    tekst = antwoord.get_data(as_text=True)
    assert "opgeslagen" in tekst
    assert WACHTWOORD not in tekst
    assert EMAIL in tekst
    assert opslag.lees_icloud()["wachtwoord"] == WACHTWOORD
    assert opslag.lees_icloud()["aan"] is True

    class NepClient:
        def __init__(self, email, wachtwoord, opener=None, timeout=20):
            assert wachtwoord == WACHTWOORD
            assert email == EMAIL

        def agenda_lijst(self):
            return [{
                "naam": "Gezin",
                "label": "Gezin",
                "url": AGENDA,
            }]

    monkeypatch.setattr(main, "IcloudClient", NepClient)
    token = csrf_uit(tekst)
    gevonden = client.post(
        "/instellingen/icloud/agendas",
        data={"csrf_token": token},
        headers=INGRESS,
        follow_redirects=True,
    )
    lijst = gevonden.get_data(as_text=True)
    assert "Gezin" in lijst
    assert WACHTWOORD not in lijst
    token = csrf_uit(lijst)
    gekozen = client.post(
        "/instellingen/icloud/kiezen",
        data={"csrf_token": token, "agenda": "0"},
        headers=INGRESS,
        follow_redirects=True,
    )
    assert "Agenda gekozen: Gezin" in gekozen.get_data(as_text=True)
    assert opslag.lees_icloud()["agenda_url"] == AGENDA

    def weiger(self, *args, **kwargs):
        raise IcloudFout("Apple weigerde het e-mailadres of het app-wachtwoord.", 401)

    monkeypatch.setattr(NepClient, "agenda_lijst", weiger)
    token = csrf_uit(gekozen.get_data(as_text=True))
    fout = client.post(
        "/instellingen/icloud/agendas",
        data={"csrf_token": token},
        headers=INGRESS,
        follow_redirects=True,
    )
    fouttekst = fout.get_data(as_text=True)
    assert "weigerde" in fouttekst
    assert WACHTWOORD not in fouttekst


def test_opruim_knop_komt_pas_na_het_voorbeeld(client, monkeypatch):
    import main

    _zet_icloud()
    pagina = client.get("/instellingen", headers=INGRESS)
    html = pagina.get_data(as_text=True)
    assert "Deze afspraken verwijderen" not in html
    token = csrf_uit(html)
    opgeslagen = client.post(
        "/instellingen/icloud",
        data={
            "csrf_token": token,
            "deel": "opruimen",
            "opruimen": "ja",
            "marker": MARKER,
        },
        headers=INGRESS,
        follow_redirects=True,
    )
    tekst = opgeslagen.get_data(as_text=True)
    assert "Voorbeeld bekijken" in tekst
    assert "Deze afspraken verwijderen" not in tekst
    assert opslag.lees_icloud()["aan"] is True

    def nep_voorbeeld(opslag_arg, vandaag, client=None):
        opslag.zet_icloud_voorbeeld({
            "token": "voorbeeld-token",
            "marker": MARKER,
            "agenda_url": AGENDA,
            "afspraken": [{"href": AGENDA + "x.ics", "titel": "Oude dienst", "wanneer": "2026-10-12"}],
        })
        return {"token": "voorbeeld-token", "afspraken": [{"titel": "Oude dienst", "wanneer": "2026-10-12"}]}

    monkeypatch.setattr(main, "voorbeeld_oude_afspraken", nep_voorbeeld)
    token = csrf_uit(tekst)
    voorbeeld = client.post(
        "/instellingen/icloud/voorbeeld",
        data={"csrf_token": token},
        headers=INGRESS,
        follow_redirects=True,
    )
    lijst = voorbeeld.get_data(as_text=True)
    assert "Oude dienst" in lijst
    assert "nog niets verwijderd" in lijst
    assert "Deze afspraken verwijderen" in lijst

    def nep_weg(opslag_arg, gekregen, client=None):
        assert gekregen == "voorbeeld-token"
        return {"verwijderd": 1, "overgeslagen": 0}

    monkeypatch.setattr(main, "verwijder_voorbeeld", nep_weg)
    token = csrf_uit(lijst)
    weg = client.post(
        "/instellingen/icloud/opruimen",
        data={"csrf_token": token, "token": "voorbeeld-token"},
        headers=INGRESS,
        follow_redirects=True,
    )
    assert "1 oude afspraak verwijderd" in weg.get_data(as_text=True)
    assert "Niets overgeslagen" in weg.get_data(as_text=True)


def test_sync_schrijft_daarna_de_agenda(monkeypatch):
    import main

    monkeypatch.setattr(
        main,
        "synchroniseer",
        lambda *args, **kwargs: {"weken": 1, "periodes": 0, "waarschuwingen": []},
    )
    gezien = {}

    def nep(opslag_arg, vandaag, client=None):
        gezien["vandaag"] = vandaag
        return {"gedaan": True, "aangemaakt": 1, "bijgewerkt": 0, "verwijderd": 0, "fout": ""}

    monkeypatch.setattr(main, "spiegel_naar_icloud", nep)
    uitkomst, tekst = main.voer_sync_uit()
    assert uitkomst == "gelukt"
    assert gezien["vandaag"] == main.nu().date()
    assert "Agenda: 1 nieuw" in tekst


def test_marker_is_standaard_auto_added_en_opruimen_staat_uit():
    inst = opslag.lees_icloud()
    assert inst["marker"] == "[AUTO-ADDED]"
    assert inst["opruimen"] is False
    assert opslag.alarm_uren() == 2


def test_feed_gebruikt_de_ingestelde_herinnering(client):
    opslag.zet_alarm_uren(3)
    opslag.bewaar_diensten([_dienst()])
    token = opslag.agenda_token()
    ics = client.get(f"/agenda/{token}.ics").get_data(as_text=True)
    kern = kern_van_ics(ics)
    assert kern["samenvatting"] == "18:00 - Bouwmarkt Voorbeeld"
    assert "Locatie: Bouwmarkt Voorbeeld (BV01)" in kern["omschrijving"]
    assert kern["omschrijving"].endswith("[AUTO-ADDED]")
    assert kern["alarm"] == "-PT3H"
    assert "X-ROOSTER-APP" not in ics
    assert "LOCATION" not in ics


def test_andere_herinnering_werkt_de_afspraak_bij():
    inst = _zet_icloud()
    opslag.bewaar_diensten([_dienst()])
    nep = NepAgenda()
    spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    opslag.zet_alarm_uren(1)
    nep.geschreven.clear()
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert verslag["bijgewerkt"] == 1
    assert "TRIGGER:-PT1H" in nep.geschreven[-1][1]
    assert inst["kenmerk"] in nep.geschreven[-1][1]


def test_kern_negeert_het_tijdstempel():
    _uid, ics = ics_voor_icloud(_dienst(), None, "ab12", nu=__import__("datetime").datetime(2026, 10, 10, tzinfo=__import__("datetime").timezone.utc))
    andere = ics.replace("DTSTAMP:20261010T000000Z", "DTSTAMP:20261011T010000Z")
    assert kern_van_ics(ics)["samenvatting"] == "18:00 - Bouwmarkt Voorbeeld"
    assert kern_van_ics(ics)["start"] == kern_van_ics(andere)["start"]
    from agenda import zelfde_afspraak
    assert zelfde_afspraak(kern_van_ics(ics), kern_van_ics(andere))
