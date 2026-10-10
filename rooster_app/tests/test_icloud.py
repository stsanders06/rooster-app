"""iCloud-agenda tegen een nagebootste CalDAV-server.

Geen echte Apple-account, geen echt app-wachtwoord, geen echte namen.
"""
import os
from datetime import date

import pytest

import opslag
from agenda import ics_voor_icloud, kern_van_ics, uid_dienst, uid_voor_icloud
from conftest import INGRESS, csrf_uit
from icloud import (
    IcloudClient,
    IcloudFout,
    _gewenste_afspraken,
    spiegel_naar_icloud,
    tekst_van_verslag,
    verwijder_vorige_voorbeeld,
    voorbeeld_vorige_agenda,
)
from manus import ManusFout

EMAIL = "voorbeeld@icloud.com"
WACHTWOORD = "abcd-efgh-ijkl-mnop"
AGENDA = "https://p01-caldav.icloud.com/123/calendars/gezin/"
ANDERE = "https://p01-caldav.icloud.com/123/calendars/werk/"
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
        "uniek": uid_dienst(date(2026, 10, 10)),
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


def _ics_scriptable(
    wanneer="20261012T090000",
    einde="20261012T170000",
    uid="scriptable-1@icloud.com",
    samenvatting="17:00 - Bouwmarkt Voorbeeld",
    notitie=None,
    extra=None,
):
    if notitie is None:
        notitie = "\\n".join([
            "Locatie: Bouwmarkt Voorbeeld (BV01)",
            "Afdeling: 03 - Voorbeeld",
            "Werktijd: 6u15m",
            "Pauze: 0u45m",
            "",
            "[AUTO-ADDED]",
        ])
    regels = [
        "BEGIN:VCALENDAR",
        "BEGIN:VTIMEZONE",
        "TZID:Europe/Amsterdam",
        "BEGIN:DAYLIGHT",
        "DTSTART:19700329T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
        "END:DAYLIGHT",
        "END:VTIMEZONE",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTART;TZID=Europe/Amsterdam:{wanneer}",
        f"DTEND;TZID=Europe/Amsterdam:{einde}",
        f"SUMMARY:{samenvatting}",
        f"DESCRIPTION:{notitie}",
    ]
    if extra:
        regels.extend(extra)
    regels.extend(["END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(regels)


def _ics_familie():
    return "\r\n".join([
        "BEGIN:VCALENDAR",
        "BEGIN:VEVENT",
        "UID:oma@icloud.com",
        "DTSTART;TZID=Europe/Amsterdam:20261012T150000",
        "DTEND;TZID=Europe/Amsterdam:20261012T180000",
        "SUMMARY:Verjaardag van oma",
        "DESCRIPTION:taart\\n\\n[AUTO-ADDED]",
        "END:VEVENT",
        "END:VCALENDAR",
    ])


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
        "ics": _ics_familie(),
    }
    scriptable = {
        "href": "https://p01-caldav.icloud.com/123/calendars/gezin/scriptable.ics",
        "etag": '"scr"',
        "ics": _ics_scriptable(),
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
    nep = NepAgenda(extra=[buiten, vreemd, verdwenen, scriptable])
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert verslag["gedaan"] is True
    assert verslag["aangemaakt"] == 2
    assert verslag["verwijderd"] == 1
    assert verslag["verwijderd"] == 1
    assert nep.verwijderd[0][0] == verdwenen["href"]
    assert all(href != vreemd["href"] for href, _etag, _kenmerk in nep.verwijderd)
    assert all(href != buiten["href"] for href, _etag, _kenmerk in nep.verwijderd)
    assert all(href != scriptable["href"] for href, _etag, _kenmerk in nep.verwijderd)
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
    assert "2 nieuw" in opslag.lees_icloud_status()["verslag"]
    assert "al gelijk" not in opslag.lees_icloud_status()["verslag"]

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


def test_put_met_verouderde_etag_zet_een_weggehaalde_afspraak_opnieuw():
    class Opener:
        def __init__(self):
            self.aanroepen = []

        def __call__(self, methode, url, headers, body, timeout):
            self.aanroepen.append((methode, headers.get("If-Match"), headers.get("If-None-Match")))
            if methode == "PUT" and headers.get("If-Match"):
                return 404, {}, b""
            if methode == "GET":
                return 404, {}, b""
            if methode == "PUT" and headers.get("If-None-Match") == "*":
                return 201, {"ETag": '"terug"'}, b""
            return 500, {}, b""

    opener = Opener()
    client = IcloudClient(EMAIL, WACHTWOORD, opener=opener)
    href = "https://p01-caldav.icloud.com/123/calendars/gezin/dienst.ics"
    client.schrijf(href, "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", '"weg"', "kenmerk")
    assert opener.aanroepen == [
        ("PUT", '"weg"', None),
        ("PUT", None, "*"),
    ]


def test_lege_agenda_zet_elke_dienst_een_keer_terug():
    inst = _zet_icloud()
    rijen = [
        _dienst(uniek="dienst-2026-10-10-540-1080-3@rooster-app"),
        _dienst(uniek=uid_dienst(date(2026, 10, 10), "42")),
        _dienst(
            datum=date(2026, 10, 11),
            start_minuten=10 * 60,
            eind_minuten=15 * 60,
            pauze_minuten=0,
            totaal_minuten=300,
            uniek=uid_dienst(date(2026, 10, 11), "7"),
        ),
    ]
    with opslag.verbinding() as conn:
        for dienst in rijen:
            conn.execute(
                """
                INSERT INTO diensten (
                    datum, start_minuten, eind_minuten, pauze_minuten, totaal_minuten,
                    winkel, winkel_code, afdeling, afdeling_code, afdeling_id, pauzes_json, uniek
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?)
                """,
                (
                    dienst["datum"].isoformat(),
                    dienst["start_minuten"],
                    dienst["eind_minuten"],
                    dienst["pauze_minuten"],
                    dienst["totaal_minuten"],
                    dienst["winkel"],
                    dienst["winkel_code"],
                    dienst["afdeling"],
                    dienst["afdeling_code"],
                    dienst["afdeling_id"],
                    dienst["uniek"],
                ),
            )
    with opslag.verbinding() as conn:
        assert conn.execute("SELECT COUNT(*) FROM diensten").fetchone()[0] == 3
    assert len(opslag.alle_diensten()) == 2
    nep = NepAgenda()
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert verslag["gedaan"] is True
    assert verslag["fout"] == ""
    assert verslag["aangemaakt"] == 2
    assert verslag["bijgewerkt"] == 0
    assert verslag["verwijderd"] == 0
    assert len(nep.geschreven) == 2
    assert all(etag is None for _href, _ics, etag, _kenmerk in nep.geschreven)
    uids = {kern_van_ics(ics)["uid"] for _href, ics, _etag, _kenmerk in nep.geschreven}
    assert uid_voor_icloud(uid_dienst(date(2026, 10, 10), "42"), inst["kenmerk"]) in uids
    assert uid_voor_icloud(uid_dienst(date(2026, 10, 11), "7"), inst["kenmerk"]) in uids
    assert uid_voor_icloud("dienst-2026-10-10-540-1080-3@rooster-app", inst["kenmerk"]) not in uids
    nep.geschreven.clear()
    nep.verwijderd.clear()
    opnieuw = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert opnieuw["aangemaakt"] == 0
    assert opnieuw["bijgewerkt"] == 0
    assert opnieuw["verwijderd"] == 0
    assert opnieuw["fout"] == ""
    assert nep.geschreven == []
    assert nep.verwijderd == []


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


def test_instellingen_bewaart_het_wachtwoord_zonder_het_te_tonen(client, monkeypatch):
    import main

    pagina = client.get("/instellingen", headers=INGRESS)
    html = pagina.get_data(as_text=True)
    assert "Gedeelde iCloud-agenda" in html
    assert "account.apple.com" in html
    assert "Oude Scriptable-afspraken" not in html
    assert 'name="opruimen"' not in html
    assert "iCloud ontkoppelen" not in html
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


def test_agendalink_en_scriptable_opruimen_zijn_weg(client):
    html = client.get("/instellingen", headers=INGRESS).get_data(as_text=True)
    assert "Oude Scriptable-afspraken" not in html
    assert "Agendalink" not in html
    assert "Nieuwe link maken" not in html
    assert 'name="opruimen"' not in html
    assert 'name="extern_adres"' not in html
    assert 'name="alarm_uren"' in html
    assert "Gedeelde iCloud-agenda" in html
    assert "Agenda opnieuw vullen" not in html
    for pad in (
        "/instellingen/icloud/voorbeeld",
        "/instellingen/icloud/opruimen",
        "/instellingen/token",
        "/instellingen/adres",
        "/agenda/geheim.ics",
    ):
        assert client.get(pad, headers=INGRESS).status_code == 404


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
    assert "1 nieuw" in tekst
    assert "al gelijk" not in tekst


def test_herinnering_staat_standaard_op_twee_uur():
    assert opslag.alarm_uren() == 2


def test_oude_opruiminstelling_blijft_niet_bewaard():
    """Een bestand van 1.3.0 kan de vlag nog hebben. De volgende keer
    opslaan haalt hem weg, anders blijft een dode schakelaar in /data.
    """
    import json

    with open(opslag.ICLOUD_PATH, "w", encoding="utf-8") as bestand:
        json.dump({
            "email": EMAIL,
            "wachtwoord": WACHTWOORD,
            "aan": True,
            "agenda_url": AGENDA,
            "agenda_naam": "Gezin",
            "kenmerk": "ab12cd34",
            "opruimen": True,
            "marker": "iets-anders",
        }, bestand)
    gelezen = opslag.lees_icloud()
    assert "opruimen" not in gelezen
    assert "marker" not in gelezen
    assert gelezen["kenmerk"] == "ab12cd34"
    opslag.schrijf_icloud({"aan": True})
    with open(opslag.ICLOUD_PATH, encoding="utf-8") as bestand:
        ruw = json.load(bestand)
    assert "opruimen" not in ruw
    assert "marker" not in ruw
    assert ruw["kenmerk"] == "ab12cd34"
    assert ruw["wachtwoord"] == WACHTWOORD


def test_herinnering_komt_in_de_afspraak():
    _uid, ics = ics_voor_icloud(_dienst(), None, "ab12", alarm_uren=3)
    kern = kern_van_ics(ics)
    assert kern["samenvatting"] == "18:00 - Bouwmarkt Voorbeeld"
    assert "Locatie: Bouwmarkt Voorbeeld (BV01)" in kern["omschrijving"]
    assert kern["omschrijving"].endswith("[AUTO-ADDED]")
    assert kern["alarm"] == "-PT3H"
    assert "X-ROOSTER-APP:ab12" in ics
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


def test_andere_tijdzone_schrijft_de_afspraak_niet_opnieuw():
    _zet_icloud()
    opslag.bewaar_diensten([_dienst()])
    nep = NepAgenda()
    spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    href = nep.geschreven[-1][0]
    nep.opgeslagen[href]["ics"] = nep.opgeslagen[href]["ics"].replace(
        "TZOFFSETFROM:+0100", "TZOFFSETFROM:+0059", 1
    )
    nep.geschreven.clear()
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert verslag["bijgewerkt"] == 0
    assert verslag["aangemaakt"] == 0
    assert verslag["verwijderd"] == 0
    assert nep.geschreven == []


def test_vorige_agenda_toont_hooguit_tweehonderd():
    inst = _zet_icloud()
    extra = []
    for nummer in range(201):
        _uid, ics = ics_voor_icloud(
            _dienst(uniek=uid_dienst(date(2026, 10, 10), str(nummer))),
            None,
            inst["kenmerk"],
        )
        extra.append({
            "href": f"{ANDERE}s{nummer:03d}.ics",
            "etag": f'"{nummer}"',
            "ics": ics,
        })
    extra.append({
        "href": ANDERE + "scriptable.ics",
        "etag": '"s"',
        "ics": _ics_scriptable(),
    })
    nep = NepAgenda(extra=extra)
    opslag.zet_vorige_agenda(ANDERE, "Werk")
    voorbeeld = voorbeeld_vorige_agenda(opslag, VANDAAG, client=nep)
    assert voorbeeld["totaal"] == 201
    assert len(voorbeeld["afspraken"]) == 200
    assert nep.verwijderd == []
    verslag = verwijder_vorige_voorbeeld(opslag, voorbeeld["token"], client=nep)
    assert verslag["verwijderd"] == 200
    assert all(not href.endswith("scriptable.ics") for href, _etag, _kenmerk in nep.verwijderd)


def test_verloren_bestand_neemt_het_kenmerk_uit_de_agenda_over():
    inst = _zet_icloud()
    origineel = inst["kenmerk"]
    opslag.bewaar_diensten([_dienst()])
    nep = NepAgenda()
    eerste = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert eerste["aangemaakt"] == 1
    os.remove(opslag.ICLOUD_PATH)
    opslag.schrijf_icloud({
        "email": EMAIL,
        "wachtwoord": WACHTWOORD,
        "aan": True,
        "agenda_url": AGENDA,
        "agenda_naam": "Gezin",
    })
    assert opslag.lees_icloud()["kenmerk"] != origineel
    nep.geschreven.clear()
    nep.verwijderd.clear()
    opnieuw = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert opnieuw["aangemaakt"] == 0
    assert opnieuw["verwijderd"] == 0
    assert opslag.lees_icloud()["kenmerk"] == origineel


def test_leeg_kenmerk_wordt_uit_de_agenda_gelezen():
    inst = _zet_icloud()
    origineel = inst["kenmerk"]
    opslag.bewaar_diensten([_dienst()])
    nep = NepAgenda()
    spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    ruw = open(opslag.ICLOUD_PATH, encoding="utf-8").read()
    import json
    data = json.loads(ruw)
    data["kenmerk"] = ""
    opslag.schrijf_bestand_0600(opslag.ICLOUD_PATH, json.dumps(data))
    nep.geschreven.clear()
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert verslag["aangemaakt"] == 0
    assert verslag["verwijderd"] == 0
    assert opslag.lees_icloud()["kenmerk"] == origineel


def test_meerdere_kenmerken_maken_geen_tweede_reeks():
    _zet_icloud()
    opslag.bewaar_diensten([_dienst()])
    _, een = ics_voor_icloud(_dienst(), None, "aaaa1111")
    _, twee = ics_voor_icloud(
        _dienst(datum=date(2026, 10, 11), uniek=uid_dienst(date(2026, 10, 11), "9")),
        None,
        "bbbb2222",
    )
    nep = NepAgenda(extra=[
        {"href": AGENDA + "a.ics", "etag": '"1"', "ics": een},
        {"href": AGENDA + "b.ics", "etag": '"2"', "ics": twee},
    ])
    ruw = __import__("json").loads(open(opslag.ICLOUD_PATH, encoding="utf-8").read())
    ruw["kenmerk"] = ""
    opslag.schrijf_bestand_0600(opslag.ICLOUD_PATH, __import__("json").dumps(ruw))
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert verslag["gedaan"] is False
    assert "tweede reeks" in verslag["fout"]
    assert nep.geschreven == []


def test_dubbele_afspraak_van_ons_gaat_weg_een_familieafspraak_blijft():
    inst = _zet_icloud()
    nieuw = _dienst(uniek=uid_dienst(date(2026, 10, 10), "42"))
    oud = _dienst(uniek="dienst-2026-10-10-540-1080-3@rooster-app")
    with opslag.verbinding() as conn:
        for dienst in (oud, nieuw):
            conn.execute(
                """
                INSERT INTO diensten (
                    datum, start_minuten, eind_minuten, pauze_minuten, totaal_minuten,
                    winkel, winkel_code, afdeling, afdeling_code, afdeling_id, pauzes_json, uniek
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?)
                """,
                (
                    dienst["datum"].isoformat(),
                    dienst["start_minuten"],
                    dienst["eind_minuten"],
                    dienst["pauze_minuten"],
                    dienst["totaal_minuten"],
                    dienst["winkel"],
                    dienst["winkel_code"],
                    dienst["afdeling"],
                    dienst["afdeling_code"],
                    dienst["afdeling_id"],
                    dienst["uniek"],
                ),
            )
    assert opslag.ruim_dubbele_diensten() == 1
    assert [dienst["uniek"] for dienst in opslag.alle_diensten()] == [nieuw["uniek"]]
    _uid_oud, ics_oud = ics_voor_icloud(oud, None, inst["kenmerk"])
    _uid_nieuw, ics_nieuw = ics_voor_icloud(nieuw, None, inst["kenmerk"])
    familie = {
        "href": AGENDA + "familie.ics",
        "etag": '"fam"',
        "ics": _ics_familie(),
    }
    nep = NepAgenda(extra=[
        {"href": AGENDA + "oud.ics", "etag": '"oud"', "ics": ics_oud},
        {"href": AGENDA + "nieuw.ics", "etag": '"nieuw"', "ics": ics_nieuw},
        familie,
    ])
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert verslag["gedaan"] is True
    assert verslag["aangemaakt"] == 0
    assert [href for href, _etag, _kenmerk in nep.verwijderd] == [AGENDA + "oud.ics"]
    assert all(href != familie["href"] for href, _etag, _kenmerk in nep.verwijderd)


def test_verschoven_tijd_werkt_de_afspraak_bij():
    _zet_icloud()
    dienst = _dienst(uniek=uid_dienst(date(2026, 10, 10), "42"))
    opslag.bewaar_diensten([dienst])
    nep = NepAgenda()
    eerste = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert eerste["aangemaakt"] == 1
    later = dict(dienst)
    later["start_minuten"] = 10 * 60
    later["eind_minuten"] = 17 * 60
    opslag.vervang_week(date(2026, 10, 10), date(2026, 10, 10), [later])
    nep.geschreven.clear()
    nep.verwijderd.clear()
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert verslag["bijgewerkt"] == 1
    assert verslag["aangemaakt"] == 0
    assert verslag["verwijderd"] == 0
    assert "20261010T100000" in nep.geschreven[-1][1]


def test_authorization_wordt_opnieuw_gezet_naar_een_andere_icloud_host():
    import base64

    verwacht = "Basic " + base64.b64encode(f"{EMAIL}:{WACHTWOORD}".encode()).decode()
    gezien = []

    def opener(methode, url, headers, body, timeout):
        gezien.append((url, headers.get("Authorization"), body))
        if url == "https://caldav.icloud.com/x":
            return 302, {"Location": "https://p01-caldav.icloud.com/x"}, b""
        return 204, {}, b""

    client = IcloudClient(EMAIL, WACHTWOORD, opener=opener)
    status, _koppen, _ruw, _eind = client._verzoek(
        "PROPFIND",
        "https://caldav.icloud.com/x",
        {"Authorization": "Basic fout", "Depth": "0"},
        b"<xml/>",
    )
    assert status == 204
    assert [auth for _url, auth, _body in gezien] == [verwacht, verwacht]
    assert gezien[1][0] == "https://p01-caldav.icloud.com/x"
    assert gezien[1][2] == b"<xml/>"
    assert "Basic fout" not in [auth for _url, auth, _body in gezien]


def test_opener_volgt_een_redirect_niet_zelf():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    from icloud import standaard_opener

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/eerste":
                self.send_response(302)
                self.send_header("Location", "/tweede")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"tweede")

        def log_message(self, fmt, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _koppen, body = standaard_opener(
            "GET", f"http://127.0.0.1:{server.server_address[1]}/eerste", {}, None, 2
        )
    finally:
        server.shutdown()
    assert status == 302
    assert b"tweede" not in body


def test_vorige_agenda_verwijdert_alleen_eigen_afspraken():
    inst = _zet_icloud()
    _uid, eigen = ics_voor_icloud(_dienst(), None, inst["kenmerk"])
    nep = NepAgenda(extra=[
        {"href": ANDERE + "eigen.ics", "etag": '"e"', "ics": eigen},
        {"href": ANDERE + "familie.ics", "etag": '"f"', "ics": _ics_familie()},
        {"href": ANDERE + "scriptable.ics", "etag": '"s"', "ics": _ics_scriptable()},
    ])
    opslag.zet_vorige_agenda(ANDERE, "Werk")
    voorbeeld = __import__("icloud").voorbeeld_vorige_agenda(opslag, VANDAAG, client=nep)
    assert [regel["titel"] for regel in voorbeeld["afspraken"]] == ["18:00 - Bouwmarkt Voorbeeld"]
    assert nep.verwijderd == []
    verslag = __import__("icloud").verwijder_vorige_voorbeeld(opslag, voorbeeld["token"], client=nep)
    assert verslag["verwijderd"] == 1
    assert nep.verwijderd[0][0].endswith("eigen.ics")
    assert opslag.lees_vorige_agenda() is None


def test_wisselen_biedt_de_vorige_agenda_aan(client):
    _zet_icloud()
    opslag.zet_icloud_agendas([
        {"naam": "Gezin", "label": "Gezin", "url": AGENDA},
        {"naam": "Werk", "label": "Werk", "url": ANDERE},
    ])
    pagina = client.get("/instellingen", headers=INGRESS)
    token = csrf_uit(pagina.get_data(as_text=True))
    gekozen = client.post(
        "/instellingen/icloud/kiezen",
        data={"csrf_token": token, "agenda": "1"},
        headers=INGRESS,
        follow_redirects=True,
    )
    tekst = gekozen.get_data(as_text=True)
    assert "Agenda gekozen: Werk" in tekst
    assert "vorige agenda" in tekst
    assert "Voorbeeld van de vorige agenda" in tekst
    assert opslag.lees_vorige_agenda()["url"] == AGENDA
    assert opslag.lees_icloud()["agenda_url"] == ANDERE


def test_ontkoppelen_haalt_het_wachtwoord_weg(client):
    inst = _zet_icloud()
    pagina = client.get("/instellingen", headers=INGRESS)
    html = pagina.get_data(as_text=True)
    assert "iCloud ontkoppelen" in html
    token = csrf_uit(html)
    zonder = client.post("/instellingen/icloud/ontkoppelen", data={}, headers=INGRESS)
    assert zonder.status_code == 400
    assert opslag.lees_icloud()["wachtwoord"] == WACHTWOORD
    weg = client.post(
        "/instellingen/icloud/ontkoppelen",
        data={"csrf_token": token},
        headers=INGRESS,
        follow_redirects=True,
    )
    tekst = weg.get_data(as_text=True)
    assert "ontkoppeld" in tekst
    assert WACHTWOORD not in tekst
    assert EMAIL not in tekst
    bewaard = opslag.lees_icloud()
    assert bewaard["wachtwoord"] == ""
    assert bewaard["email"] == ""
    assert bewaard["aan"] is False
    assert bewaard["kenmerk"] == inst["kenmerk"]


def test_dienst_en_deeldagverlof_blijven_twee_afspraken():
    opslag.bewaar_diensten([_dienst()])
    opslag.vervang_verlof_van_jaren([2026], [{
        "van": date(2026, 10, 10),
        "tot": date(2026, 10, 10),
        "code": "V",
        "omschrijving": "",
        "memo": "",
        "soort": "Vakantie",
        "gedeeltelijk": True,
        "van_minuten": 18 * 60,
        "tot_minuten": 23 * 60 + 59,
        "aangevraagd": False,
        "uniek": "verlof-id-42@rooster-app",
    }])
    _zet_icloud()
    kenmerk = opslag.lees_icloud()["kenmerk"]
    gewenst = _gewenste_afspraken(
        opslag, kenmerk, AGENDA, date(2026, 10, 1), date(2026, 11, 15)
    )
    assert len(gewenst) == 2
    dienst = next(item["ics"] for item in gewenst.values() if "DTSTART;TZID=Europe/Amsterdam:20261010T090000" in item["ics"])
    verlof = next(item["ics"] for item in gewenst.values() if "Vrij vanaf 18:00" in item["ics"])
    assert "BEGIN:VALARM" in dienst
    assert "BEGIN:VALARM" not in verlof
    assert "DTSTART;TZID=Europe/Amsterdam:20261010T180000" in verlof


def test_geannuleerde_afspraak_wordt_opnieuw_gezet():
    """STATUS:CANCELLED toont de agenda-app niet. Dezelfde titel is dan niet 'al gelijk'."""
    from agenda import zelfde_afspraak

    inst = _zet_icloud()
    opslag.bewaar_diensten([_dienst()])
    uid, ics = ics_voor_icloud(_dienst(), None, inst["kenmerk"])
    geannuleerd = ics.replace("END:VEVENT", "STATUS:CANCELLED\r\nEND:VEVENT")
    assert zelfde_afspraak(kern_van_ics(ics), kern_van_ics(geannuleerd)) is False
    nep = NepAgenda(extra=[{
        "href": AGENDA + "weg.ics",
        "etag": '"weg"',
        "ics": geannuleerd,
    }])
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert verslag["aangemaakt"] == 0
    assert verslag["bijgewerkt"] == 1
    assert "STATUS:CANCELLED" not in nep.geschreven[-1][1]
    assert uid in nep.geschreven[-1][1]


def test_opnieuw_vullen_overschrijft_ook_een_gelijke_afspraak(client, monkeypatch):
    import main

    _zet_icloud(agenda_naam="Diensten voorbeeld")
    gezien = {}

    def nep(opslag_arg, vandaag, client=None, opnieuw=False):
        gezien["opnieuw"] = opnieuw
        gezien["vandaag"] = vandaag
        return {
            "gedaan": True,
            "agenda_naam": "Diensten voorbeeld",
            "gevonden": 2,
            "aangemaakt": 0,
            "bijgewerkt": 2,
            "verwijderd": 0,
            "fout": "",
        }

    monkeypatch.setattr(main, "spiegel_naar_icloud", nep)
    pagina = client.get("/instellingen", headers=INGRESS)
    html = pagina.get_data(as_text=True)
    assert "Agenda opnieuw vullen" in html
    assert "al gelijk" not in html
    antwoord = client.post(
        "/instellingen/icloud/opnieuw",
        data={"csrf_token": csrf_uit(html)},
        headers=INGRESS,
        follow_redirects=True,
    )
    tekst = antwoord.get_data(as_text=True)
    assert gezien["opnieuw"] is True
    assert gezien["vandaag"] == main.nu().date()
    assert "al gelijk" not in tekst
    assert "Diensten voorbeeld: 2 gevonden, 0 nieuw, 2 bijgewerkt, 0 verwijderd." in tekst


def test_dode_agenda_url_schrijft_naar_de_agenda_met_dezelfde_naam():
    oud = "https://p01-caldav.icloud.com/123/calendars/oud/"
    nieuw = "https://p01-caldav.icloud.com/123/calendars/werken/"
    _zet_icloud(agenda_url=oud, agenda_naam="Diensten voorbeeld")
    opslag.bewaar_diensten([_dienst()])

    class Verhuis:
        def __init__(self):
            self.geschreven = []
            self.gevraagd = []

        def agenda_info(self, url):
            self.gevraagd.append(url)
            if url == oud:
                raise IcloudFout("weg", 404)
            return {"naam": "Diensten voorbeeld", "url": url}

        def agenda_lijst(self):
            return [
                {"naam": "Thuis", "label": "Thuis", "url": AGENDA},
                {"naam": "Diensten voorbeeld", "label": "Diensten voorbeeld", "url": nieuw},
            ]

        def afspraken(self, url, van, tot):
            assert url == nieuw
            return []

        def schrijf(self, href, ics, etag, kenmerk):
            self.geschreven.append(href)

    nep = Verhuis()
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=nep)
    assert verslag["gedaan"] is True
    assert verslag["aangemaakt"] == 1
    assert nep.geschreven[0].startswith(nieuw)
    assert opslag.lees_icloud()["agenda_url"] == nieuw
    assert "Agenda Diensten voorbeeld: 0 gevonden, 1 nieuw" in opslag.lees_icloud_status()["verslag"]


WERK = "https://p01-caldav.icloud.com/123/calendars/werken/"


def _xml_tekst(tekst: str) -> str:
    return tekst.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class NepCalDav:
    """CalDAV-opener. Leden zijn de waarheid; het rapport mag daar van afwijken.

    Zo blijft een weggegooide afspraak in een verouderd calendar-query staan
    terwijl PROPFIND hem niet meer noemt.
    """

    def __init__(self):
        self.leden = {}
        self.rapport_vast = None
        self.aanroepen = []
        self.puts = []
        self.teller = 0
        self.naam = "Diensten voorbeeld"

    def __call__(self, methode, url, headers, body, timeout):
        diepte = headers.get("Depth")
        lading = body.decode("utf-8") if isinstance(body, bytes) else (body or "")
        self.aanroepen.append((methode, url, diepte, lading))
        if methode == "PROPFIND" and diepte == "0":
            return 207, {}, self._info(url)
        if methode == "PROPFIND" and diepte == "1":
            return 207, {}, self._leden_xml()
        if methode == "REPORT":
            return 207, {}, self._rapport()
        if methode == "GET":
            return self._get(url)
        if methode == "PUT":
            self.puts.append((url, headers.get("If-Match"), headers.get("If-None-Match")))
            return self._put(url, headers, lading)
        if methode == "DELETE":
            self.leden.pop(url, None)
            return 204, {}, b""
        return 500, {}, b"onverwacht"

    def _pad(self, url: str) -> str:
        from urllib.parse import urlparse

        return urlparse(url).path

    def _info(self, url: str) -> bytes:
        return f"""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>{self._pad(url)}</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>{self.naam}</d:displayname>
        <d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>""".encode()

    def _leden_xml(self) -> bytes:
        stukken = ["""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/123/calendars/werken/</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype><d:collection/></d:resourcetype>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>"""]
        for href, waarde in self.leden.items():
            stukken.append(f"""
  <d:response>
    <d:href>{self._pad(href)}</d:href>
    <d:propstat>
      <d:prop>
        <d:getetag>{_xml_tekst(waarde["etag"])}</d:getetag>
        <d:resourcetype/>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>""")
        stukken.append("\n</d:multistatus>")
        return "".join(stukken).encode()

    def _rapport(self) -> bytes:
        bron = self.leden if self.rapport_vast is None else {
            item["href"]: item for item in self.rapport_vast
        }
        stukken = ["""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">"""]
        for href, waarde in bron.items():
            stukken.append(f"""
  <d:response>
    <d:href>{self._pad(href)}</d:href>
    <d:propstat>
      <d:prop>
        <d:getetag>{_xml_tekst(waarde["etag"])}</d:getetag>
        <c:calendar-data>{_xml_tekst(waarde["ics"])}</c:calendar-data>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>""")
        stukken.append("\n</d:multistatus>")
        return "".join(stukken).encode()

    def _get(self, url):
        waarde = self.leden.get(url)
        if waarde is None:
            return 404, {}, b""
        return 200, {"ETag": waarde["etag"]}, waarde["ics"].encode()

    def _put(self, url, headers, ics):
        if headers.get("If-None-Match") == "*" and url in self.leden:
            return 412, {}, b""
        if headers.get("If-Match") and url not in self.leden:
            return 404, {}, b""
        self.teller += 1
        self.leden[url] = {"etag": f'"e{self.teller}"', "ics": ics}
        return 201, {"ETag": f'"e{self.teller}"'}, b""


def test_verwijderde_afspraken_komen_terug_ook_als_lokaal_staat_dat_ze_er_zijn():
    """De agenda-app gooide ze weg. Een oud rapport en een hash in /data zeggen van niet.

    De ledenlijst is leeg, dus ze worden opnieuw gezet. De balk noemt de tellingen.
    """
    import json
    import re

    import main

    inst = _zet_icloud(agenda_url=WERK, agenda_naam="Diensten voorbeeld")
    diensten = [
        _dienst(),
        _dienst(
            datum=date(2026, 10, 11),
            start_minuten=12 * 60,
            eind_minuten=18 * 60,
            pauze_minuten=30,
            totaal_minuten=330,
            uniek=uid_dienst(date(2026, 10, 11), "7"),
        ),
    ]
    opslag.bewaar_diensten(diensten)
    server = NepCalDav()
    client = IcloudClient(EMAIL, WACHTWOORD, opener=server)
    eerste = spiegel_naar_icloud(opslag, VANDAAG, client=client)
    assert eerste["aangemaakt"] == 2
    assert eerste["agenda_naam"] == "Diensten voorbeeld"
    assert all(href.startswith(WERK) for href in server.leden)
    rapporten = [lading for methode, _url, _diepte, lading in server.aanroepen if methode == "REPORT"]
    assert rapporten
    assert "calendar-query" in rapporten[0]
    assert re.search(r'start="\d{8}T\d{6}Z"', rapporten[0])
    assert re.search(r'end="\d{8}T\d{6}Z"', rapporten[0])
    assert all(
        diepte == "1"
        for methode, _url, diepte, _lading in server.aanroepen
        if methode == "REPORT"
    )

    # Weggegooid in de agenda-app: de ledenlijst is leeg, het rapport niet.
    vast = [
        {"href": href, "etag": waarde["etag"], "ics": waarde["ics"]}
        for href, waarde in server.leden.items()
    ]
    familie_href = WERK + "familie.ics"
    server.leden = {
        familie_href: {"etag": '"fam"', "ics": _ics_familie()},
    }
    server.rapport_vast = vast + [{
        "href": familie_href,
        "etag": '"fam"',
        "ics": _ics_familie(),
    }]
    with open(opslag.ICLOUD_PATH, encoding="utf-8") as bestand:
        lokaal = json.load(bestand)
    lokaal["ctag"] = "oud-ctag"
    lokaal["sync_token"] = "https://p01-caldav.icloud.com/123/calendars/werken/sync/1"
    lokaal["laatste_hash"] = "niet-gebruiken"
    lokaal["hrefs"] = [item["href"] for item in vast]
    with open(opslag.ICLOUD_PATH, "w", encoding="utf-8") as bestand:
        json.dump(lokaal, bestand)
    server.aanroepen.clear()
    server.puts.clear()

    opnieuw = spiegel_naar_icloud(opslag, VANDAAG, client=client)
    assert opnieuw["gedaan"] is True
    assert opnieuw["gevonden"] == 0
    assert opnieuw["aangemaakt"] == 2
    assert opnieuw["verwijderd"] == 0
    assert familie_href in server.leden
    assert _ics_familie() == server.leden[familie_href]["ics"]
    assert len(server.puts) == 2
    assert all(url.startswith(WERK) for url, _match, _geen in server.puts)
    assert all(geen == "*" and match is None for _url, match, geen in server.puts)
    assert not any("sync-collection" in (lading or "") or "niet-gebruiken" in (lading or "") or "oud-ctag" in (lading or "") for _m, _u, _d, lading in server.aanroepen)
    assert sum(1 for methode, _u, _d, _l in server.aanroepen if methode == "REPORT") == 1
    tekst = tekst_van_verslag(opnieuw)
    assert "al gelijk" not in tekst
    assert tekst == "Agenda Diensten voorbeeld: 0 gevonden, 2 nieuw, 0 bijgewerkt, 0 verwijderd"
    assert opslag.lees_icloud()["kenmerk"] == inst["kenmerk"]
    # De hash in het bestand is geen bron. Hij mag blijven staan; hij stuurt niets aan.
    with open(opslag.ICLOUD_PATH, encoding="utf-8") as bestand:
        nog = json.load(bestand)
    assert nog.get("laatste_hash") == "niet-gebruiken"
    assert "laatste_hash" not in opslag.lees_icloud()


def test_leeg_rapport_leest_eigen_bestanden_en_maakt_geen_tweede_reeks():
    inst = _zet_icloud(agenda_url=WERK, agenda_naam="Diensten voorbeeld")
    opslag.bewaar_diensten([_dienst()])
    server = NepCalDav()
    client = IcloudClient(EMAIL, WACHTWOORD, opener=server)
    spiegel_naar_icloud(opslag, VANDAAG, client=client)
    assert len(server.leden) == 1
    server.rapport_vast = []
    server.aanroepen.clear()
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=client)
    assert verslag["aangemaakt"] == 0
    assert verslag["bijgewerkt"] == 0
    assert verslag["gevonden"] == 1
    assert len(server.leden) == 1
    assert inst["kenmerk"] in next(iter(server.leden))


def test_opnieuw_vullen_schrijft_ook_als_de_tekst_gelijk_is():
    _zet_icloud(agenda_url=WERK, agenda_naam="Diensten voorbeeld")
    opslag.bewaar_diensten([_dienst()])
    server = NepCalDav()
    client = IcloudClient(EMAIL, WACHTWOORD, opener=server)
    spiegel_naar_icloud(opslag, VANDAAG, client=client)
    server.aanroepen.clear()
    verslag = spiegel_naar_icloud(opslag, VANDAAG, client=client, opnieuw=True)
    assert verslag["gevonden"] == 1
    assert verslag["bijgewerkt"] == 1
    assert verslag["aangemaakt"] == 0
    puts = [url for methode, url, _d, _l in server.aanroepen if methode == "PUT"]
    assert len(puts) == 1
    assert puts[0].startswith(WERK)

