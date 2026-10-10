"""Sync tegen een nagebootste API. Er gaat niets het netwerk op.

De vormen volgen de MyManus-antwoorden, met verzonnen id's, een verzonnen
winkel en ronde uren. Niets hiervan is een echte persoon of loonstrook.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

import opslag
from conftest import INGRESS
from datums import datum_naar_excel, excel_naar_datum
from manus import AlleenLezenFout, ManusClient, ManusFout
from synchronisatie import (
    _dienst_uit_entry,
    _geen_afgesloten_periodes,
    diensten_uit_rooster,
    identiteit_uit,
    synchroniseer,
)


WINKEL = "Bouwmarkt Voorbeeld"
NODE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
MEDEWERKER = "11111111-2222-3333-4444-555555555555"


def _iso(dag: date) -> int:
    return datum_naar_excel(dag)


class Nep:
    def __init__(self):
        self.aanroepen = []
        self.token = None
        self.eerst_401 = False
        self.login_tellers = 0

    def login(self, naam, wachtwoord):
        assert wachtwoord
        self.login_tellers += 1
        self.aanroepen.append(("POST", "token"))
        self.token = "nep-token"
        return {"access_token": "nep-token", "expires_in": 86400}

    def get_json(self, pad):
        self.aanroepen.append(("GET", pad))
        if self.eerst_401 and pad == "user/me":
            self.eerst_401 = False
            raise ManusFout("verlopen", 401)
        return self._antwoord(pad)

    def _antwoord(self, pad):
        if pad == "user/me":
            return {
                "nodeId": NODE,
                "nodeName": WINKEL,
                "employeeId": MEDEWERKER,
                "funcName": "Verkoop",
            }
        if pad == "user/own":
            return {"employeeId": MEDEWERKER, "nodeId": NODE, "nodeName": WINKEL}
        if "/schedule/" in pad and pad.endswith("/fromData"):
            return {
                "nodes": {NODE: {"id": NODE, "name": WINKEL, "code": "BV01"}},
                "departments": {"3": {"id": 3, "name": "Verkoop", "code": 7}},
                "schedule": [{
                    "date": _iso(date(2026, 10, 10)),
                    "entries": [{
                        "startTime": 9 * 60,
                        "endTime": 18 * 60,
                        "breakTime": 45,
                        "totalTime": 495,
                        "departmentId": 3,
                        "nodeId": NODE,
                        "notes": "",
                        "breaks": [{"from": 12 * 60, "to": 12 * 60 + 45, "duration": 45}],
                    }],
                    "vacation": [],
                }],
            }
        if pad.endswith("/upcoming"):
            return {
                str(_iso(date(2026, 10, 13))): [{
                    "startTime": 13 * 60,
                    "endTime": 21 * 60,
                    "breakTime": 30,
                    "totalTime": 450,
                    "departmentId": 4,
                    "departmentName": "Magazijn",
                    "departmentCode": "12",
                    "nodeName": WINKEL,
                    "nodeCode": "BV01",
                    "breaks": [],
                }]
            }
        if "/vacation-status" in pad:
            return {
                "currentSumBalance": {"end": {"hours": 1800}},
                "endSumBalance": {
                    "end": {"hours": 2400},
                    "holidayEntitlement": {"hours": 2400},
                    "used": {"hours": 0},
                },
            }
        if "/vacation/" in pad:
            return [{
                "fromDate": _iso(date(2026, 11, 4)),
                "toDate": _iso(date(2026, 11, 5)),
                "abbr": "V",
                "hcodeDescription": "Vakantie",
                "description": "Verlof",
                "memo": "dit memo mag niet worden opgeslagen",
            }]
        if "lastagreedperiod-summary" in pad:
            return _samenvatting(
                9001, "september 2026", date(2026, 9, 1), date(2026, 9, 30), 4800, 300, 600
            )
        raise ManusFout(f"onverwacht pad {pad}", 404)


def _periode(periode_id, naam, van, tot) -> dict:
    return {
        "id": periode_id,
        "fromDate": _iso(van),
        "toDate": _iso(tot),
        "year": van.year,
        "name": naam,
        "group": "maand",
    }


def _samenvatting(periode_id, naam, van, tot, gerealiseerd, compensatie=0, plusmin=0) -> dict:
    """Zelfde vorm als periodsummary en lastagreedperiod-summary.

    balances en weeks horen in het antwoord, niet in de database.
    """
    return {
        "selectedPeriod": {
            "id": periode_id,
            "fromDate": _iso(van),
            "toDate": _iso(tot),
            "year": van.year,
            "name": naam,
        },
        "realizedHours": gerealiseerd,
        "compensationGained": compensatie,
        "plusMinusGained": plusmin,
        "vacationUsed": 0,
        "allowances": 0,
        "balances": [{"name": "verzonnen", "hours": 60}],
        "weeks": [{"week": 31, "realizedHours": 2400}],
    }


class PeriodesNep(Nep):
    """Jaarlijsten en per-periode-samenvattingen, nog steeds zonder netwerk."""

    def __init__(
        self,
        lijsten=None,
        samenvattingen=None,
        laatste=None,
        lijst_fout=None,
        samenvatting_fout=None,
    ):
        super().__init__()
        self.lijsten = lijsten if lijsten is not None else {}
        self.samenvattingen = samenvattingen or {}
        self.laatste = laatste
        self.lijst_fout = lijst_fout
        self.samenvatting_fout = samenvatting_fout

    def _antwoord(self, pad):
        if "/salary-period/" in pad:
            jaar = int(pad.rstrip("/").rsplit("/", 1)[-1])
            if jaar in self.lijsten:
                waarde = self.lijsten[jaar]
                if isinstance(waarde, Exception):
                    raise waarde
                return waarde
            if self.lijst_fout is not None:
                raise self.lijst_fout
            raise ManusFout(
                "geen periodes",
                400,
                {"detail": {"message": "ERR_NO_AGREED_PERIODS"}},
            )
        if "periodsummary/" in pad:
            if self.samenvatting_fout is not None:
                raise self.samenvatting_fout
            periode_id = int(pad.rstrip("/").rsplit("/", 1)[-1])
            if periode_id not in self.samenvattingen:
                raise ManusFout("geen overzicht", 404)
            return self.samenvattingen[periode_id]
        if "lastagreedperiod-summary" in pad:
            return super()._antwoord(pad)
        if f"lastagreedperiod/{MEDEWERKER}" in pad:
            if isinstance(self.laatste, Exception):
                raise self.laatste
            if self.laatste is None:
                raise ManusFout("geen laatste", 404)
            return self.laatste
        return super()._antwoord(pad)


def test_komend_zonder_code_laat_een_bekende_code_staan():
    """Upcoming heeft lang niet altijd een code. Die van het weekrooster blijft."""
    origineel = _dienst_uit_entry(
        date(2026, 10, 13),
        {"startTime": 13 * 60, "endTime": 21 * 60, "breakTime": 30, "totalTime": 450},
        WINKEL,
        "Magazijn",
        4,
        "BV01",
        "12",
    )
    opslag.bewaar_diensten([origineel])
    zonder = _dienst_uit_entry(
        date(2026, 10, 13),
        {"startTime": 13 * 60, "endTime": 21 * 60, "breakTime": 30, "totalTime": 450, "nodeName": WINKEL},
        WINKEL,
        "Magazijn",
        4,
    )
    opslag.bewaar_diensten([zonder])
    bewaard = opslag.alle_diensten()[0]
    assert bewaard["winkel_code"] == "BV01"
    assert bewaard["afdeling_code"] == "12"
    assert bewaard["winkel"] == WINKEL


def test_sync_slaat_dienst_periode_en_verlof_op(monkeypatch):
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    nep = Nep()
    verslag = synchroniseer(nep, opslag, date(2026, 10, 10), pauze=0, weken=[(2026, 41)])
    assert verslag["weken"] == 1
    diensten = opslag.alle_diensten()
    datums = {d["datum"] for d in diensten}
    assert date(2026, 10, 10) in datums
    assert date(2026, 10, 13) in datums
    zaterdag = next(d for d in diensten if d["datum"] == date(2026, 10, 10))
    assert zaterdag["winkel"] == WINKEL
    assert zaterdag["winkel_code"] == "BV01"
    assert zaterdag["afdeling"] == "Verkoop"
    assert zaterdag["afdeling_code"] == "07"
    dinsdag = next(d for d in diensten if d["datum"] == date(2026, 10, 13))
    assert dinsdag["afdeling_code"] == "12"
    assert dinsdag["winkel_code"] == "BV01"
    assert zaterdag["pauze_minuten"] == 45
    assert excel_naar_datum(datum_naar_excel(zaterdag["datum"])) == date(2026, 10, 10)

    periodes = opslag.alle_samenvattingen()
    assert len(periodes) == 1
    assert periodes[0]["naam"] == "september 2026"
    assert periodes[0]["van"] == date(2026, 9, 1)
    assert periodes[0]["tot"] == date(2026, 9, 30)
    assert periodes[0]["gerealiseerd_minuten"] == 4800

    verloven = opslag.alle_verlof()
    assert len(verloven) == 1
    assert verloven[0]["van"] == date(2026, 11, 4)
    assert verloven[0]["tot"] == date(2026, 11, 5)
    assert "memo" not in verloven[0]["omschrijving"].lower()
    assert "opgeslagen" not in verloven[0]["omschrijving"]

    saldo = opslag.lees_verlofsaldo()
    assert saldo["nu_minuten"] == 1800
    assert verslag["waarschuwingen"] == []
    # Niet lastagreedperiod-summary: dat pad bestaat wel en is de terugval.
    assert not any("/agreedperiod-summary" in pad for _methode, pad in nep.aanroepen)


def test_sync_doet_alleen_get_naast_het_inloggen(monkeypatch):
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    nep = Nep()
    synchroniseer(nep, opslag, date(2026, 10, 10), pauze=0, weken=[(2026, 41)])
    posts = [pad for methode, pad in nep.aanroepen if methode != "GET"]
    assert posts == ["token"]
    assert all(methode in ("GET", "POST") for methode, _pad in nep.aanroepen)
    assert not any(methode in ("PUT", "PATCH", "DELETE") for methode, _pad in nep.aanroepen)


def test_een_oude_week_blijft_staan_als_hij_niet_opnieuw_wordt_opgehaald(monkeypatch):
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    opslag.bewaar_diensten([{
        "datum": date(2026, 6, 2),
        "start_minuten": 9 * 60,
        "eind_minuten": 13 * 60,
        "pauze_minuten": 0,
        "totaal_minuten": 240,
        "winkel": WINKEL,
        "afdeling": "Verkoop",
        "afdeling_id": 3,
        "pauzes": [],
        "uniek": "dienst-2026-06-02-540-780-3@rooster-app",
    }])
    synchroniseer(Nep(), opslag, date(2026, 10, 10), pauze=0, weken=[(2026, 41)])
    datums = {d["datum"] for d in opslag.alle_diensten()}
    assert date(2026, 6, 2) in datums
    assert date(2026, 10, 10) in datums


def test_401_logt_een_keer_opnieuw_in(monkeypatch):
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    nep = Nep()
    nep.eerst_401 = True
    synchroniseer(nep, opslag, date(2026, 10, 10), pauze=0, weken=[(2026, 41)])
    assert nep.login_tellers == 2
    assert opslag.alle_diensten()


def test_bewaard_token_wordt_hergebruikt(monkeypatch):
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    opslag.meta_set("access_token", "al-geldig")
    opslag.meta_set(
        "token_geldig_tot",
        (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
    )
    nep = Nep()
    synchroniseer(nep, opslag, date(2026, 10, 10), pauze=0, weken=[(2026, 41)])
    assert nep.login_tellers == 0
    assert nep.token == "al-geldig"


def test_medewerker_komt_uit_user_own_als_me_die_niet_geeft():
    wie = identiteit_uit(
        {"nodeId": NODE, "nodeName": WINKEL},
        {"employeeId": MEDEWERKER},
    )
    assert wie["employee_id"] == MEDEWERKER
    assert wie["node_id"] == NODE
    assert wie["winkel"] == WINKEL


def test_rooster_datum_10_oktober_blijft_10_oktober():
    payload = Nep()._antwoord("node/x/employee/y/schedule/2026/41/fromData")
    diensten = diensten_uit_rooster(payload, WINKEL)
    assert diensten[0]["datum"] == date(2026, 10, 10)
    assert diensten[0]["pauzes"] == [(12 * 60, 12 * 60 + 45)]


def test_client_schrijft_niets_behalve_het_inloggen():
    aangeroepen = []

    def opener(methode, url, headers, body, timeout):
        aangeroepen.append((methode, url))
        if "token" in url:
            return 200, b'{"access_token":"abc","expires_in":60}'
        return 200, b"{}"

    client = ManusClient(opener=opener)
    with pytest.raises(AlleenLezenFout):
        client._verzoek("PUT", "https://server.manus.plus/intergamma/api/node/1", {}, None)
    with pytest.raises(AlleenLezenFout):
        client._verzoek("POST", "https://server.manus.plus/intergamma/api/user/me", {}, b"{}")
    assert aangeroepen == []

    client.login("voorbeeld", "geen-echt-wachtwoord")
    assert aangeroepen[0][0] == "POST"
    assert aangeroepen[0][1].endswith("/intergamma/app/token")
    client.get_json("user/me")
    assert aangeroepen[-1][0] == "GET"
    assert aangeroepen[-1][1].endswith("/api/user/me")


def test_zonder_totaltime_gaat_de_pauze_van_elke_dienst_af():
    dag = _dienst_uit_entry(
        date(2026, 10, 6),
        {"startTime": 9 * 60, "endTime": 17 * 60, "breakTime": 30},
        "",
        "",
        1,
    )
    assert dag["totaal_minuten"] == 8 * 60 - 30


def test_nachtdienst_trekt_de_pauze_een_keer_af():
    nacht = _dienst_uit_entry(
        date(2026, 10, 9),
        {"startTime": 22 * 60, "endTime": 6 * 60, "breakTime": 30},
        "",
        "",
        1,
    )
    # 22:00 tot 06:00 is 8 uur. De pauze gaat er één keer af, niet per stuk.
    assert nacht["totaal_minuten"] == 8 * 60 - 30


def _paden(nep, stuk: str) -> list[str]:
    return [pad for methode, pad in nep.aanroepen if methode == "GET" and stuk in pad]


def _sync(nep):
    return synchroniseer(nep, opslag, date(2026, 10, 10), pauze=0, weken=[(2026, 41)])


def test_oudere_afgesloten_maand_wordt_een_keer_opgehaald(monkeypatch, client):
    """Augustus komt uit de jaarlijst, niet uit het rooster.

    2025 heeft geen afgesloten periodes. Dat is leeg, geen waarschuwing.
    De tweede sync slaat augustus over en haalt alleen de nieuwste opnieuw.
    """
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    opslag.bewaar_diensten([{
        "datum": date(2026, 8, 3),
        "start_minuten": 9 * 60,
        "eind_minuten": 13 * 60,
        "pauze_minuten": 0,
        "totaal_minuten": 4 * 60,
        "winkel": WINKEL,
        "afdeling": "Verkoop",
        "afdeling_id": 3,
        "pauzes": [],
        "uniek": "dienst-2026-08-03-540-780-3@rooster-app",
    }])
    augustus = _periode(8001, "augustus 2026", date(2026, 8, 1), date(2026, 8, 31))
    september = _periode(9001, "september 2026", date(2026, 9, 1), date(2026, 9, 30))
    nep = PeriodesNep(
        lijsten={2026: [september, augustus]},
        samenvattingen={
            8001: _samenvatting(8001, "augustus 2026", date(2026, 8, 1), date(2026, 8, 31), 80 * 60),
            9001: _samenvatting(9001, "september 2026", date(2026, 9, 1), date(2026, 9, 30), 90 * 60),
        },
        laatste=september,
    )
    verslag = _sync(nep)
    assert verslag["waarschuwingen"] == []
    assert verslag["periodes"] == 2
    assert _paden(nep, "salary-period/2025")
    assert _paden(nep, "salary-period/2026")
    assert not _paden(nep, "salary-period/2024")
    assert _paden(nep, "periodsummary/") == [
        f"additionalinfo/periodsummary/{MEDEWERKER}/8001",
        f"additionalinfo/periodsummary/{MEDEWERKER}/9001",
    ]
    assert _paden(nep, f"lastagreedperiod/{MEDEWERKER}")
    assert not _paden(nep, "lastagreedperiod-summary")
    assert not _paden(nep, "/agreedperiod-summary")

    per_id = {rij["periode_id"]: rij for rij in opslag.alle_samenvattingen()}
    assert per_id[8001]["van"] == date(2026, 8, 1)
    assert per_id[8001]["tot"] == date(2026, 8, 31)
    assert per_id[8001]["gerealiseerd_minuten"] == 80 * 60
    assert "balances" not in per_id[8001]
    assert "weeks" not in per_id[8001]

    augustus_html = client.get("/?maand=2026-08", headers=INGRESS).get_data(as_text=True)
    assert "definitief" in augustus_html
    assert "gepland/geschat" not in augustus_html
    assert "uit de afgesloten periode" in augustus_html
    assert "80,00" in augustus_html
    september_html = client.get("/?maand=2026-09", headers=INGRESS).get_data(as_text=True)
    assert "definitief" in september_html
    assert "90,00" in september_html
    oktober_html = client.get("/?maand=2026-10", headers=INGRESS).get_data(as_text=True)
    assert "gepland/geschat" in oktober_html
    assert "op het rooster" in oktober_html

    nep.aanroepen.clear()
    opnieuw = _sync(nep)
    assert opnieuw["waarschuwingen"] == []
    assert opnieuw["periodes"] == 1
    assert _paden(nep, "periodsummary/") == [f"additionalinfo/periodsummary/{MEDEWERKER}/9001"]
    assert not _paden(nep, "lastagreedperiod-summary")


def test_nieuwste_periode_volgt_de_einddatum(monkeypatch):
    """Zonder lastagreedperiod wint de laatste einddatum, niet de plek in de lijst."""
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    # Hoogste id op de oudere maand, en die staat vooraan. Allebei een val.
    augustus = _periode(9001, "augustus 2026", date(2026, 8, 1), date(2026, 8, 31))
    september = _periode(8001, "september 2026", date(2026, 9, 1), date(2026, 9, 30))
    nep = PeriodesNep(
        lijsten={2026: [augustus, september]},
        samenvattingen={
            9001: _samenvatting(9001, "augustus 2026", date(2026, 8, 1), date(2026, 8, 31), 80 * 60),
            8001: _samenvatting(8001, "september 2026", date(2026, 9, 1), date(2026, 9, 30), 90 * 60),
        },
    )
    verslag = _sync(nep)
    assert verslag["waarschuwingen"] == []
    assert {rij["periode_id"] for rij in opslag.alle_samenvattingen()} == {8001, 9001}
    nep.aanroepen.clear()
    _sync(nep)
    assert _paden(nep, "periodsummary/") == [f"additionalinfo/periodsummary/{MEDEWERKER}/8001"]


def test_jaar_zonder_periodes_via_404_geeft_geen_waarschuwing(monkeypatch):
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    september = _periode(9001, "september 2026", date(2026, 9, 1), date(2026, 9, 30))
    nep = PeriodesNep(
        lijsten={
            2025: ManusFout("weg", 404),
            2026: [september],
        },
        samenvattingen={
            9001: _samenvatting(9001, "september 2026", date(2026, 9, 1), date(2026, 9, 30), 90 * 60),
        },
        laatste=september,
    )
    verslag = _sync(nep)
    assert verslag["waarschuwingen"] == []
    assert len(opslag.alle_samenvattingen()) == 1


def test_ontbrekend_overzicht_valt_terug_op_de_laatste_samenvatting(monkeypatch):
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    september = _periode(9001, "september 2026", date(2026, 9, 1), date(2026, 9, 30))
    nep = PeriodesNep(
        lijsten={2026: [september]},
        laatste=september,
        samenvatting_fout=ManusFout("weg", 404),
    )
    verslag = _sync(nep)
    assert verslag["waarschuwingen"] == []
    assert opslag.alle_samenvattingen()[0]["gerealiseerd_minuten"] == 4800
    assert _paden(nep, "lastagreedperiod-summary")


def test_storing_bij_de_periodelijst_geeft_een_waarschuwing(monkeypatch):
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    nep = PeriodesNep(lijst_fout=ManusFout("storing", 500, {"detail": {"message": "ERR_KAPOT"}}))
    verslag = _sync(nep)
    assert any("2026" in tekst for tekst in verslag["waarschuwingen"])
    assert any("2025" in tekst for tekst in verslag["waarschuwingen"])
    assert not any("ERR_" in tekst for tekst in verslag["waarschuwingen"])
    assert opslag.alle_samenvattingen()[0]["naam"] == "september 2026"


def test_geen_afgesloten_periodes_is_geen_storing():
    assert _geen_afgesloten_periodes(ManusFout("weg", 404))
    assert _geen_afgesloten_periodes(
        ManusFout("leeg", 400, {"detail": {"message": "ERR_NO_AGREED_PERIODS"}})
    )
    assert not _geen_afgesloten_periodes(ManusFout("storing", 500))
    assert not _geen_afgesloten_periodes(
        ManusFout("storing", 500, {"detail": {"message": "ERR_KAPOT"}})
    )
    assert not _geen_afgesloten_periodes(ManusFout("sessie", 401))


def test_foutantwoord_bewaart_de_code_buiten_de_melding():
    def opener(methode, url, headers, body, timeout):
        return 400, b'{"detail":{"message":"ERR_NO_AGREED_PERIODS"}}'

    client = ManusClient(opener=opener)
    client.token = "nep-token"
    with pytest.raises(ManusFout) as gevonden:
        client.get_json(f"node/{NODE}/employee/{MEDEWERKER}/salary-period/2025")
    assert gevonden.value.status == 400
    assert gevonden.value.inhoud["detail"]["message"] == "ERR_NO_AGREED_PERIODS"
    assert "ERR_NO_AGREED_PERIODS" not in str(gevonden.value)
    assert _geen_afgesloten_periodes(gevonden.value)


def test_inlogfout_noemt_het_wachtwoord_niet():
    def opener(methode, url, headers, body, timeout):
        return 400, b'{"error":"invalid_grant"}'

    client = ManusClient(opener=opener)
    with pytest.raises(ManusFout) as gevonden:
        client.login("voorbeeld", "wachtwoord-dat-niet-in-de-fout-mag")
    assert "wachtwoord-dat-niet-in-de-fout-mag" not in str(gevonden.value)
