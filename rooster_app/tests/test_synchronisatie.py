"""Sync tegen een nagebootste API. Er gaat niets het netwerk op.

De vormen volgen de MyManus-antwoorden, met verzonnen id's, een verzonnen
winkel en ronde uren. Niets hiervan is een echte persoon of loonstrook.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

import opslag
from datums import datum_naar_excel, excel_naar_datum
from manus import AlleenLezenFout, ManusClient, ManusFout
from synchronisatie import (
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
                "nodes": {NODE: {"id": NODE, "name": WINKEL, "code": "0000"}},
                "departments": {"3": {"id": 3, "name": "Verkoop", "code": "3"}},
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
                    "nodeName": WINKEL,
                    "breaks": [],
                }]
            }
        if "/vacation-status" in pad:
            return {
                "currentSumBalance": {"end": {"hours": 1800}},
                "endSumBalance": {
                    "end": {"hours": 2160},
                    "holidayEntitlement": {"hours": 2160},
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
            return {
                "selectedPeriod": {
                    "id": 9001,
                    "fromDate": _iso(date(2026, 9, 1)),
                    "toDate": _iso(date(2026, 9, 30)),
                    "year": 2026,
                    "name": "september 2026",
                },
                "realizedHours": 4800,
                "compensationGained": 300,
                "plusMinusGained": 600,
                "vacationUsed": 0,
                "allowances": 0,
            }
        if "agreedperiod-summary" in pad:
            raise ManusFout("niet aanwezig", 404)
        raise ManusFout(f"onverwacht pad {pad}", 404)


def test_sync_slaat_dienst_periode_en_verlof_op(monkeypatch):
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    verslag = synchroniseer(Nep(), opslag, date(2026, 10, 10), pauze=0, weken=[(2026, 41)])
    assert verslag["weken"] == 1
    diensten = opslag.alle_diensten()
    datums = {d["datum"] for d in diensten}
    assert date(2026, 10, 10) in datums
    assert date(2026, 10, 13) in datums
    zaterdag = next(d for d in diensten if d["datum"] == date(2026, 10, 10))
    assert zaterdag["winkel"] == WINKEL
    assert zaterdag["afdeling"] == "Verkoop"
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


def test_inlogfout_noemt_het_wachtwoord_niet():
    def opener(methode, url, headers, body, timeout):
        return 400, b'{"error":"invalid_grant"}'

    client = ManusClient(opener=opener)
    with pytest.raises(ManusFout) as gevonden:
        client.login("voorbeeld", "wachtwoord-dat-niet-in-de-fout-mag")
    assert "wachtwoord-dat-niet-in-de-fout-mag" not in str(gevonden.value)
