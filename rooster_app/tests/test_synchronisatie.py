"""Sync tegen een nagebootste API. Er gaat niets het netwerk op.

De vormen volgen de MyManus-antwoorden, met verzonnen id's, een verzonnen
winkel en ronde uren. Niets hiervan is een echte persoon of loonstrook.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

import opslag
from conftest import INGRESS
from datums import datum_naar_excel, excel_naar_datum
from manus import AlleenLezenFout, ManusClient, ManusFout, _een_keer, _manus_url, volg_redirects
from synchronisatie import (
    _dienst_uit_entry,
    _geen_afgesloten_periodes,
    _lege_jaarlijst,
    diensten_uit_komend,
    diensten_uit_rooster,
    identiteit_uit,
    synchroniseer,
    verlof_samenvoegen,
    verlof_uit_lijst,
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
        laatste_samenvatting_fout=None,
    ):
        super().__init__()
        self.lijsten = lijsten if lijsten is not None else {}
        self.samenvattingen = samenvattingen or {}
        self.laatste = laatste
        self.lijst_fout = lijst_fout
        self.samenvatting_fout = samenvatting_fout
        self.laatste_samenvatting_fout = laatste_samenvatting_fout

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
            if self.laatste_samenvatting_fout is not None:
                raise self.laatste_samenvatting_fout
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
    # De vereenvoudigde nep heeft geen lastagreedperiod. Een 404 daar is
    # geen leeg jaar; de samenvatting daarna komt wel binnen.
    assert verslag["waarschuwingen"] == ["De laatst afgesloten periode is niet opgehaald."]
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


def _zet_rij(dienst: dict) -> None:
    with opslag.verbinding() as conn:
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
                dienst.get("pauze_minuten") or 0,
                dienst["totaal_minuten"],
                dienst.get("winkel") or "",
                dienst.get("winkel_code") or "",
                dienst.get("afdeling") or "",
                dienst.get("afdeling_code") or "",
                dienst.get("afdeling_id"),
                dienst["uniek"],
            ),
        )


def _aantal_rijen() -> int:
    with opslag.verbinding() as conn:
        return conn.execute("SELECT COUNT(*) FROM diensten").fetchone()[0]


def test_oude_sleutel_en_nieuwe_sleutel_tellen_na_migratie_een_keer():
    from overzicht import delen_van_maand
    from salaris import periode_uit_dict, standaard_periode_dicts

    dag = date(2026, 10, 10)
    later = date(2026, 10, 11)
    gemeenschappelijk = dict(
        datum=dag,
        start_minuten=9 * 60,
        eind_minuten=17 * 60,
        pauze_minuten=30,
        totaal_minuten=450,
        winkel=WINKEL,
        afdeling="Verkoop",
        afdeling_id=3,
    )
    # Sleutel van vóór 1.3.0: datum, tijden en afdeling.
    _zet_rij({**gemeenschappelijk, "uniek": "dienst-2026-10-10-540-1020-3@rooster-app"})
    _zet_rij({**gemeenschappelijk, "uniek": "dienst-2026-10-10-id-42@rooster-app"})
    # Een andere dienst, alleen onder de oude sleutel, hoort te blijven.
    _zet_rij({
        "datum": later,
        "start_minuten": 10 * 60,
        "eind_minuten": 14 * 60,
        "pauze_minuten": 0,
        "totaal_minuten": 240,
        "winkel": WINKEL,
        "afdeling": "Verkoop",
        "afdeling_id": 3,
        "uniek": "dienst-2026-10-11-600-840-3@rooster-app",
    })
    assert _aantal_rijen() == 3
    # Het leespad telt de kloktijd al één keer, ook vóór de opruiming.
    assert len(opslag.alle_diensten()) == 2
    periode = periode_uit_dict(standaard_periode_dicts()[1])
    deel = delen_van_maand(2026, 10, opslag.alle_diensten(), [], [periode], [])[0]
    assert deel.uren == Decimal("11.50")
    assert deel.gewerkte_dagen == 2

    assert opslag.ruim_dubbele_diensten() == 1
    assert _aantal_rijen() == 2
    over = opslag.alle_diensten()
    assert [dienst["uniek"] for dienst in over] == [
        "dienst-2026-10-10-id-42@rooster-app",
        "dienst-2026-10-11-600-840-3@rooster-app",
    ]
    nog = delen_van_maand(2026, 10, over, [], [periode], [])[0]
    assert nog.uren == Decimal("11.50")


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
    assert verslag["waarschuwingen"] == ["De laatst afgesloten periode is niet opgehaald."]
    assert "ERR_" not in verslag["waarschuwingen"][0]
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
    assert verslag["waarschuwingen"] == ["Een periodeoverzicht is niet opgehaald."]
    assert "ERR_" not in verslag["waarschuwingen"][0]
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
    assert not _geen_afgesloten_periodes(ManusFout("weg", 404))
    assert _lege_jaarlijst(ManusFout("weg", 404))
    assert _geen_afgesloten_periodes(
        ManusFout("leeg", 400, {"detail": {"message": "ERR_NO_AGREED_PERIODS"}})
    )
    assert _lege_jaarlijst(
        ManusFout("leeg", 400, {"detail": {"message": "ERR_NO_AGREED_PERIODS"}})
    )
    assert not _geen_afgesloten_periodes(ManusFout("storing", 500))
    assert not _lege_jaarlijst(ManusFout("storing", 500, {"detail": {"message": "ERR_KAPOT"}}))
    assert not _geen_afgesloten_periodes(ManusFout("sessie", 401))
    assert not _lege_jaarlijst(ManusFout("sessie", 401))


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


def test_code_geen_periodes_blijft_stil_een_andere_404_niet(monkeypatch, caplog):
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    september = _periode(9001, "september 2026", date(2026, 9, 1), date(2026, 9, 30))
    nep = PeriodesNep(
        lijsten={2026: [september]},
        laatste=september,
        samenvatting_fout=ManusFout(
            "leeg", 400, {"detail": {"message": "ERR_NO_AGREED_PERIODS"}}
        ),
        laatste_samenvatting_fout=ManusFout("weg", 404, {"detail": {"message": "ERR_KAPOT"}}),
    )
    with caplog.at_level(logging.WARNING, logger="rooster"):
        verslag = _sync(nep)
    assert verslag["waarschuwingen"] == ["Een periodeoverzicht is niet opgehaald."]
    assert "ERR_" not in verslag["waarschuwingen"][0]
    assert "Een periodeoverzicht is niet opgehaald." in caplog.text


class _ZelfdeDienstNep(Nep):
    """Weekrooster en upcoming beschrijven dezelfde dienst met een ander id."""

    def _antwoord(self, pad):
        if "/schedule/" in pad and pad.endswith("/fromData"):
            return {
                "nodes": {NODE: {"name": WINKEL, "code": "BV01"}},
                "departments": {"3": {"name": "Verkoop", "code": "03"}},
                "schedule": [
                    {
                        "date": _iso(date(2026, 10, 10)),
                        "entries": [{
                            "id": "42",
                            "startTime": 9 * 60,
                            "endTime": 17 * 60,
                            "breakTime": 30,
                            "totalTime": 450,
                            "departmentId": 3,
                            "nodeId": NODE,
                        }],
                    },
                    {
                        "date": _iso(date(2026, 10, 11)),
                        "entries": [{
                            "id": "7",
                            "startTime": 10 * 60,
                            "endTime": 14 * 60,
                            "breakTime": 0,
                            "totalTime": 240,
                            "departmentId": 3,
                            "nodeId": NODE,
                        }],
                    },
                ],
            }
        if pad.endswith("/upcoming"):
            return {
                str(_iso(date(2026, 10, 10))): [{
                    "scheduleEntryId": "99",
                    "startTime": 9 * 60,
                    "endTime": 17 * 60,
                    "breakTime": 30,
                    "totalTime": 450,
                    "departmentId": 3,
                }],
            }
        return super()._antwoord(pad)


def test_week_en_komend_tellen_dezelfde_dienst_een_keer(monkeypatch):
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    synchroniseer(_ZelfdeDienstNep(), opslag, date(2026, 10, 10), pauze=0, weken=[(2026, 41)])
    diensten = opslag.alle_diensten()
    assert len(diensten) == 2
    zaterdag = next(dienst for dienst in diensten if dienst["datum"] == date(2026, 10, 10))
    zondag = next(dienst for dienst in diensten if dienst["datum"] == date(2026, 10, 11))
    assert zaterdag["uniek"] == "dienst-2026-10-10-id-99@rooster-app"
    assert zaterdag["totaal_minuten"] == 450
    assert zondag["uniek"] == "dienst-2026-10-11-id-7@rooster-app"
    minuten = sum(dienst["totaal_minuten"] for dienst in diensten)
    assert minuten == 450 + 240


def test_uid_blijft_gelijk_als_de_tijd_schuift():
    dag = datum_naar_excel(date(2026, 10, 10))

    def rooster(tijden):
        return {
            "nodes": {NODE: {"name": WINKEL, "code": "BV01"}},
            "departments": {"3": {"name": "Verkoop", "code": "03"}},
            "schedule": [{
                "date": dag,
                "entries": [
                    {
                        "id": "42",
                        "startTime": tijden[0],
                        "endTime": tijden[1],
                        "breakTime": 0,
                        "totalTime": tijden[1] - tijden[0],
                        "departmentId": 3,
                        "nodeId": NODE,
                    },
                    {
                        "startTime": tijden[2],
                        "endTime": tijden[3],
                        "breakTime": 0,
                        "totalTime": tijden[3] - tijden[2],
                        "departmentId": 3,
                        "nodeId": NODE,
                    },
                    {
                        "entryId": "",
                        "startTime": tijden[4],
                        "endTime": tijden[5],
                        "breakTime": 0,
                        "totalTime": tijden[5] - tijden[4],
                        "departmentId": 3,
                        "nodeId": NODE,
                    },
                ],
            }],
        }

    # De latere dienst staat eerst. De volgorde is die van de API, niet van de klok.
    vroeg = (18 * 60, 21 * 60, 9 * 60, 12 * 60, 13 * 60, 16 * 60)
    later = (19 * 60, 22 * 60, 10 * 60, 13 * 60, 14 * 60, 17 * 60)
    een = diensten_uit_rooster(rooster(vroeg), WINKEL)
    twee = diensten_uit_rooster(rooster(later), WINKEL)
    assert [dienst["uniek"] for dienst in een] == [dienst["uniek"] for dienst in twee]
    assert een[0]["uniek"] == "dienst-2026-10-10-id-42@rooster-app"
    assert een[1]["uniek"].endswith("nr-1@rooster-app")
    assert een[2]["uniek"].endswith("nr-2@rooster-app")
    assert een[0]["start_minuten"] != twee[0]["start_minuten"]

    komend = diensten_uit_komend({
        str(dag): [{
            "scheduleEntryId": "42",
            "startTime": 10 * 60,
            "endTime": 17 * 60,
            "breakTime": 0,
            "totalTime": 7 * 60,
            "departmentId": 3,
        }],
    }, WINKEL)
    assert komend[0]["uniek"] == een[0]["uniek"]


def test_redirect_stuurt_het_token_niet_naar_een_andere_host():
    aanroepen = []

    def verstuur(methode, url, headers, body):
        aanroepen.append((methode, url, headers.get("Authorization"), body))
        if url.endswith("/token"):
            return 302, {"Location": "https://evil.example/vang"}, b""
        return 200, {}, b"ok"

    with pytest.raises(ManusFout) as gevonden:
        volg_redirects(
            verstuur,
            "POST",
            "https://server.manus.plus/intergamma/app/token",
            {"Authorization": "Bearer geheim", "Accept": "application/json"},
            b"password=geheim",
            _manus_url,
            ManusFout,
        )
    assert "bekende server" in str(gevonden.value)
    assert aanroepen == [(
        "POST",
        "https://server.manus.plus/intergamma/app/token",
        "Bearer geheim",
        b"password=geheim",
    )]


def test_redirect_naar_dezelfde_host_zet_het_token_opnieuw():
    aanroepen = []

    def verstuur(methode, url, headers, body):
        aanroepen.append((methode, url, dict(headers), body))
        if url.endswith("/a"):
            return 307, {"Location": "https://server.manus.plus/intergamma/api/b"}, b""
        return 200, {}, b"ok"

    status, _koppen, ruw = volg_redirects(
        verstuur,
        "GET",
        "https://server.manus.plus/intergamma/api/a",
        {"Authorization": "Bearer geheim"},
        None,
        _manus_url,
        ManusFout,
    )
    assert status == 200
    assert ruw == b"ok"
    assert aanroepen[1][2]["Authorization"] == "Bearer geheim"
    assert aanroepen[0][2] is not aanroepen[1][2]


def test_redirect_van_een_post_laat_de_body_niet_meegaan():
    aanroepen = []

    def verstuur(methode, url, headers, body):
        aanroepen.append((methode, url, headers.get("Authorization"), body))
        if url.endswith("/token"):
            return 302, {"Location": "https://server.manus.plus/intergamma/app/token2"}, b""
        return 200, {}, b"ok"

    volg_redirects(
        verstuur,
        "POST",
        "https://server.manus.plus/intergamma/app/token",
        {"Authorization": "Bearer geheim"},
        b"password=geheim",
        _manus_url,
        ManusFout,
    )
    assert aanroepen[1][0] == "GET"
    assert aanroepen[1][2] == "Bearer geheim"
    assert aanroepen[1][3] is None


def test_manus_opener_volgt_een_redirect_niet_zelf():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

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
        status, _koppen, body = _een_keer(
            "GET", f"http://127.0.0.1:{server.server_address[1]}/eerste", {}, None, 2
        )
    finally:
        server.shutdown()
    assert status == 302
    assert b"tweede" not in body


def _vrij_vanaf_achttien():
    return {
        "id": 42,
        "fromDate": _iso(date(2026, 10, 10)),
        "toDate": _iso(date(2026, 10, 10)),
        "fromTime": 18 * 60,
        "toTime": None,
        "fromDateTime": "2026-10-10T18:00:00",
        "toDateTime": "2026-10-10T23:59:00",
        "abbr": "V",
        "description": "Verlof (handmatige invoer)",
        "memo": "tandarts",
        "hcodeDescription": "Vakantie",
        "processed": True,
    }


def test_deeldagverlof_bewaart_de_kloktijd_en_het_id():
    from agenda import titel_verlof

    verlof = verlof_uit_lijst([_vrij_vanaf_achttien()])[0]
    assert verlof["gedeeltelijk"] is True
    assert verlof["van_minuten"] == 18 * 60
    assert verlof["tot_minuten"] == 23 * 60 + 59
    assert verlof["omschrijving"] == ""
    assert verlof["memo"] == "tandarts"
    assert verlof["soort"] == "Vakantie"
    assert verlof["bron_id"] == "42"
    assert verlof["uniek"] == "verlof-id-42@rooster-app"
    assert titel_verlof(verlof) == "Vrij vanaf 18:00"


def test_verlof_tot_een_kloktijd_en_een_reeks_met_twee_tijden():
    from agenda import titel_verlof

    tot_twaalf = verlof_uit_lijst([{
        "id": 1,
        "fromDate": _iso(date(2026, 10, 10)),
        "toDate": _iso(date(2026, 10, 10)),
        "fromTime": None,
        "toTime": 12 * 60,
        "fromDateTime": "2026-10-10T00:00:00",
        "toDateTime": "2026-10-10T12:00:00",
    }])[0]
    assert tot_twaalf["van_minuten"] == 0
    assert tot_twaalf["tot_minuten"] == 12 * 60
    assert titel_verlof(tot_twaalf) == "Vrij tot 12:00"

    reeks = verlof_uit_lijst([{
        "id": 2,
        "fromDate": _iso(date(2026, 10, 10)),
        "toDate": _iso(date(2026, 10, 12)),
        "fromTime": 9 * 60,
        "toTime": 17 * 60,
    }])[0]
    assert reeks["van"] == date(2026, 10, 10)
    assert reeks["tot"] == date(2026, 10, 12)
    assert titel_verlof(reeks) == "Vrij 09:00-17:00"


def test_hele_dag_blijft_een_hele_dag_zonder_kloktijd():
    verlof = verlof_uit_lijst([{
        "fromDate": _iso(date(2026, 11, 4)),
        "toDate": _iso(date(2026, 11, 5)),
        "fromTime": None,
        "toTime": None,
        "fromDateTime": "2026-11-04T00:00:00",
        "toDateTime": "2026-11-05T23:59:00",
        "abbr": "V",
    }])[0]
    assert verlof["gedeeltelijk"] is False
    assert verlof["van_minuten"] is None
    assert verlof["uniek"].startswith("verlof-2026-11-04-")


def test_aanvraag_open_krijgt_een_voorvoegsel_en_afgewezen_vervalt():
    from agenda import titel_verlof

    openstaand = verlof_uit_lijst([{
        "id": 8,
        "fromDate": _iso(date(2026, 12, 1)),
        "toDate": _iso(date(2026, 12, 1)),
        "processed": False,
    }])[0]
    assert openstaand["aangevraagd"] is True
    assert titel_verlof(openstaand) == "(aangevraagd) Vrij"
    assert verlof_uit_lijst([{
        "id": 9,
        "fromDate": _iso(date(2026, 12, 2)),
        "toDate": _iso(date(2026, 12, 2)),
        "processed": False,
        "rejectionNote": "past niet",
    }]) == []


def test_verlofboek_en_aanvraag_worden_ontdubbeld_op_id():
    geboekt = [{
        "id": 7,
        "fromDate": _iso(date(2026, 11, 4)),
        "toDate": _iso(date(2026, 11, 5)),
        "processed": True,
    }]
    aanvragen = [
        {"id": 7, "fromDate": _iso(date(2026, 11, 4)), "toDate": _iso(date(2026, 11, 5)), "processed": False},
        {"id": 8, "fromDate": _iso(date(2026, 12, 1)), "toDate": _iso(date(2026, 12, 1)), "processed": True},
        {"id": 9, "fromDate": _iso(date(2026, 12, 2)), "toDate": _iso(date(2026, 12, 2)), "rejectionNote": "nee"},
    ]
    uit = verlof_samenvoegen(geboekt, aanvragen)
    ids = [verlof["bron_id"] for verlof in uit]
    assert ids == ["7", "8"]
    assert uit[0]["aangevraagd"] is False


def test_sync_haalt_aanvragen_en_laat_het_rooster_tarief_liggen(monkeypatch):
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    rijen = opslag.perioden_dicts()
    rijen[1]["uurloon"] = "8.00"
    opslag.vervang_perioden(rijen)

    class MetTarief(Nep):
        def _antwoord(self, pad):
            if "/schedule/" in pad and pad.endswith("/fromData"):
                rooster = super()._antwoord(pad)
                # Een tarief in het rooster is geen loon. Het mag nergens belanden.
                rooster["contracts"] = [{
                    "id": 3,
                    "hourRate": 12.24,
                    "grossRate": 99.5,
                    "functionName": "Verkoop",
                    "fromDate": _iso(date(2026, 10, 10)),
                    "workingHours": 1800,
                }]
                return rooster
            if "/vacationrequest/" in pad:
                return [_vrij_vanaf_achttien()]
            return super()._antwoord(pad)

    nep = MetTarief()
    synchroniseer(nep, opslag, date(2026, 10, 10), pauze=0, weken=[(2026, 41)])
    assert any("/vacationrequest/" in pad for _methode, pad in nep.aanroepen)
    deeldag = next(
        verlof for verlof in opslag.alle_verlof()
        if verlof["uniek"] == "verlof-id-42@rooster-app"
    )
    assert deeldag["titel"] == "Vrij vanaf 18:00"
    assert deeldag["memo"] == "tandarts"
    assert opslag.perioden_dicts()[1]["uurloon"] == "8.00"
    with opslag.verbinding() as conn:
        tabellen = [rij[0] for rij in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        ruw = " ".join(
            " ".join("" if waarde is None else str(waarde) for waarde in rij)
            for rij in conn.execute("SELECT * FROM contractperioden")
        )
    assert "manus_contract" not in tabellen
    assert "12.24" not in ruw
    assert "99.5" not in ruw


class _WeekFout(PeriodesNep):
    """Weekrooster met een gekozen fout, en verder een stille periodelijst."""

    def __init__(self, fouten):
        september = _periode(9001, "september 2026", date(2026, 9, 1), date(2026, 9, 30))
        super().__init__(
            lijsten={2026: [september]},
            samenvattingen={
                9001: _samenvatting(9001, "september 2026", date(2026, 9, 1), date(2026, 9, 30), 90 * 60),
            },
            laatste=september,
        )
        self.fouten = fouten

    def _antwoord(self, pad):
        if "/schedule/" in pad and pad.endswith("/fromData"):
            delen = pad.split("/")
            sleutel = (int(delen[-3]), int(delen[-2]))
            if sleutel in self.fouten:
                raise self.fouten[sleutel]
        return super()._antwoord(pad)


def _dienst_op(dag):
    return {
        "datum": dag,
        "start_minuten": 9 * 60,
        "eind_minuten": 17 * 60,
        "pauze_minuten": 30,
        "totaal_minuten": 450,
        "winkel": WINKEL,
        "afdeling": "Verkoop",
        "afdeling_id": 3,
        "pauzes": [],
        "uniek": f"dienst-{dag.isoformat()}@rooster-app",
    }


def test_week_voorbij_het_gepubliceerde_rooster_blijft_stil(monkeypatch):
    """Week 46 komt nog in het venster, maar MyManus heeft hem niet.

    Een fout die geen 404 is, hoort dan niet in de balk. De dagen die er
    al stonden, worden niet leeggemaakt.
    """
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    dag = date(2026, 11, 10)
    opslag.bewaar_diensten([_dienst_op(dag)])
    nep = _WeekFout({
        (2026, 46): ManusFout("MyManus antwoordde met een fout (400).", 400),
    })
    verslag = synchroniseer(
        nep, opslag, date(2026, 10, 10), pauze=0, weken=[(2026, 45), (2026, 46)],
    )
    assert verslag["weken"] == 1
    assert verslag["waarschuwingen"] == []
    assert any(dienst["datum"] == dag for dienst in opslag.alle_diensten())


def test_weekfout_tussen_gepubliceerde_weken_noemt_de_reden(monkeypatch):
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    nep = _WeekFout({
        (2026, 45): ManusFout("MyManus antwoordde met een fout (500).", 500),
    })
    verslag = synchroniseer(
        nep,
        opslag,
        date(2026, 10, 10),
        pauze=0,
        weken=[(2026, 44), (2026, 45), (2026, 46)],
    )
    assert verslag["weken"] == 2
    assert verslag["waarschuwingen"] == [
        "Week 45 van 2026 niet opgehaald: MyManus antwoordde met een fout (500)."
    ]
    assert "ERR_" not in verslag["waarschuwingen"][0]


def test_enige_week_die_mislukt_blijft_een_waarschuwing(monkeypatch):
    """Zonder één gelukte week is het geen 'nog niet gepubliceerd'."""
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    nep = _WeekFout({
        (2026, 46): ManusFout("MyManus is niet bereikbaar. Probeer het later opnieuw."),
    })
    verslag = synchroniseer(
        nep, opslag, date(2026, 10, 10), pauze=0, weken=[(2026, 46)],
    )
    assert verslag["weken"] == 0
    assert len(verslag["waarschuwingen"]) == 1
    assert "niet bereikbaar" in verslag["waarschuwingen"][0]


def test_404_op_een_week_blijft_leeg_zonder_melding(monkeypatch):
    monkeypatch.setattr(opslag, "inloggegevens", lambda: ("voorbeeld", "geheim", "app"))
    nep = _WeekFout({(2026, 46): ManusFout("MyManus kent dit adres niet.", 404)})
    verslag = synchroniseer(
        nep, opslag, date(2026, 10, 10), pauze=0, weken=[(2026, 45), (2026, 46)],
    )
    assert verslag["weken"] == 1
    assert verslag["waarschuwingen"] == []
