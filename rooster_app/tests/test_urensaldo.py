"""Urensaldo met verzonnen uren. Geen loonstrook, geen persoon.

Het uurloon is 15, verzonnen. De tests controleren de formule: contracturen
naar rato, afgesloten maanden uit de samenvatting, de rest uit het rooster,
en een jaar dat weer op nul begint.
"""
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import opslag
from conftest import INGRESS
from salaris import contracturen_per_maand, periode_uit_dict, standaard_periode_dicts
from synchronisatie import samenvatting_uit
from urensaldo import jaarsaldo

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
VANDAAG = date(2026, 10, 10)


def _vast(vanaf, tot=None, uren="30", loon="15", naam="Parttime"):
    rij = standaard_periode_dicts()[1]
    rij["naam"] = naam
    rij["geldig_vanaf"] = vanaf.isoformat()
    rij["geldig_tot"] = "" if tot is None else tot.isoformat()
    rij["uren_per_week"] = uren
    rij["uurloon"] = loon
    rij["vast_maandloon"] = True
    return periode_uit_dict(rij)


def _hulpkracht():
    return periode_uit_dict(standaard_periode_dicts()[0])


def _dienst(dag, minuten, uniek):
    return {
        "datum": dag,
        "start_minuten": 9 * 60,
        "eind_minuten": 9 * 60 + minuten,
        "pauze_minuten": 0,
        "totaal_minuten": minuten,
        "winkel": "Bouwmarkt Voorbeeld",
        "afdeling": "Verkoop",
        "afdeling_id": 1,
        "pauzes": [],
        "uniek": uniek,
    }


def _verlof(van, tot):
    return {
        "van": van,
        "tot": tot,
        "gedeeltelijk": False,
        "code": "V",
        "omschrijving": "Vakantie",
        "uniek": f"verlof-{van.isoformat()}",
    }


def _overzicht(perioden, diensten=None, verloven=None, samenvattingen=None, jaar=2026, vandaag=VANDAAG):
    return jaarsaldo(
        jaar,
        perioden,
        diensten or [],
        verloven or [],
        samenvattingen or [],
        vandaag,
    )


def _maand(overzicht, maand):
    return next(rij for rij in overzicht.maanden if rij.maand == maand)


def test_eerste_maand_telt_naar_rato_en_negeert_uren_ervoor():
    """15 oktober is dag 15 van 31. Contracturen × 17/31, niet de volle 130.

    Een dienst en een vrije dag vóór de start horen er niet bij. Verlof
    erna wel: een vijfde van de weekuren.
    """
    periode = _vast(date(2026, 10, 15))
    overzicht = _overzicht(
        [periode],
        diensten=[
            _dienst(date(2026, 10, 10), 8 * 60, "ervoor"),
            _dienst(date(2026, 10, 16), 450, "vrijdag"),
            _dienst(date(2026, 10, 20), 8 * 60, "dinsdag"),
        ],
        verloven=[
            _verlof(date(2026, 10, 14), date(2026, 10, 14)),
            _verlof(date(2026, 10, 21), date(2026, 10, 21)),
        ],
    )
    oktober = _maand(overzicht, 10)
    assert oktober.naar_rato
    assert oktober.contracturen == Decimal("71.29")
    assert oktober.contracturen != contracturen_per_maand(periode)
    assert oktober.gewerkt == Decimal("21.50")
    assert oktober.plusmin == Decimal("-49.79")
    assert oktober.status == "gepland"
    assert oktober.cumulatief == Decimal("-49.79")
    assert overzicht.regel_voor(10).gepland_uren == Decimal("-49.79")
    assert overzicht.regel_voor(10).heeft_gepland


def test_volle_maand_blijft_weekuren_maal_52_gedeeld_door_12():
    periode = _vast(date(2026, 10, 1))
    overzicht = _overzicht([periode], vandaag=date(2026, 10, 10))
    oktober = _maand(overzicht, 10)
    assert not oktober.naar_rato
    assert oktober.contracturen == Decimal("130.00")


def test_afgesloten_maand_komt_uit_mymanus_en_geplande_uit_het_rooster():
    """September is dicht. Een dienst in september telt niet nog een keer.

    Oktober staat nog op het rooster. Het saldo van MyManus blijft ernaast
    en wordt niet bij het onze opgeteld.
    """
    periode = _vast(date(2026, 9, 1))
    september = {
        "periode_id": 9001,
        "naam": "september 2026",
        "van": date(2026, 9, 1),
        "tot": date(2026, 9, 30),
        "jaar": 2026,
        "gerealiseerd_minuten": 120 * 60,
        "compensatie_minuten": 0,
        "plusmin_minuten": 90,
        "verlof_minuten": 10 * 60,
        "toeslagen": 0,
        "manus_begin_minuten": 210,
        "manus_eind_minuten": 300,
    }
    overzicht = _overzicht(
        [periode],
        diensten=[
            _dienst(date(2026, 9, 3), 40 * 60, "september-negeren"),
            _dienst(date(2026, 10, 6), 140 * 60, "oktober"),
        ],
        samenvattingen=[september],
    )
    dicht = _maand(overzicht, 9)
    open_maand = _maand(overzicht, 10)
    assert dicht.status == "definitief"
    assert dicht.gewerkt == Decimal("130.00")
    assert dicht.plusmin == Decimal("0.00")
    assert dicht.manus_plusmin == Decimal("1.50")
    assert dicht.manus_eind == Decimal("5.00")
    assert dicht.cumulatief == Decimal("0.00")
    assert dicht.cumulatief != dicht.manus_eind

    assert open_maand.status == "gepland"
    assert open_maand.gewerkt == Decimal("140.00")
    assert open_maand.plusmin == Decimal("10.00")
    assert open_maand.cumulatief == Decimal("10.00")
    assert open_maand.manus_eind is None

    t_m_oktober = overzicht.regel_voor(10)
    assert t_m_oktober.cumulatief == Decimal("10.00")
    assert t_m_oktober.gepland_uren == Decimal("10.00")
    assert t_m_oktober.manus_uren == Decimal("5.00")
    assert t_m_oktober.manus_maand == "september"
    assert t_m_oktober.indicatie == Decimal("150.00")
    assert t_m_oktober.cumulatief != t_m_oktober.manus_uren

    t_m_september = overzicht.regel_voor(9)
    assert not t_m_september.heeft_gepland
    assert t_m_september.manus_maand is None
    assert t_m_september.manus_uren == Decimal("5.00")

    assert _maand(overzicht, 11).status == "geen rooster"
    assert _maand(overzicht, 11).cumulatief is None
    assert overzicht.projectie == Decimal("10.00")
    assert overzicht.projectie_gepland == Decimal("10.00")
    assert overzicht.rooster_zin == (
        "November en december hebben nog geen rooster en zitten niet in dit getal."
    )
    assert all(rij.maand >= 9 for rij in overzicht.maanden)


def test_afgesloten_deel_van_de_maand_houdt_de_contracturen_naar_rato():
    periode = _vast(date(2026, 10, 15))
    overzicht = _overzicht(
        [periode],
        diensten=[_dienst(date(2026, 10, 20), 8 * 60, "rooster")],
        samenvattingen=[{
            "periode_id": 1001,
            "naam": "oktober 2026",
            "van": date(2026, 10, 15),
            "tot": date(2026, 10, 31),
            "jaar": 2026,
            "gerealiseerd_minuten": 40 * 60,
            "plusmin_minuten": None,
            "verlof_minuten": 0,
            "manus_eind_minuten": None,
        }],
    )
    oktober = _maand(overzicht, 10)
    assert oktober.status == "definitief"
    assert oktober.contracturen == Decimal("71.29")
    assert oktober.gewerkt == Decimal("40.00")
    assert oktober.plusmin == Decimal("-31.29")


def test_twee_contracten_in_een_maand_tellen_allebei_naar_rato():
    eerste = _vast(date(2026, 10, 1), date(2026, 10, 15), uren="20", naam="Eerste")
    tweede = _vast(date(2026, 10, 16), uren="30", naam="Tweede")
    overzicht = _overzicht([eerste, tweede])
    oktober = _maand(overzicht, 10)
    assert oktober.naar_rato
    assert oktober.contracturen == Decimal("109.03")


def test_saldo_begint_in_januari_opnieuw():
    periode = _vast(date(2026, 12, 1))
    samenvatting = {
        "periode_id": 1201,
        "naam": "december 2026",
        "van": date(2026, 12, 1),
        "tot": date(2026, 12, 31),
        "jaar": 2026,
        "gerealiseerd_minuten": 134 * 60,
        "plusmin_minuten": 4 * 60,
        "verlof_minuten": 0,
        "manus_eind_minuten": 4 * 60,
    }
    dienst = [_dienst(date(2027, 1, 4), 8 * 60, "januari")]
    einde = _overzicht([periode], samenvattingen=[samenvatting], jaar=2026)
    begin = _overzicht([periode], diensten=dienst, samenvattingen=[samenvatting], jaar=2027)
    assert _maand(einde, 12).plusmin == Decimal("4.00")
    assert _maand(einde, 12).cumulatief == Decimal("4.00")
    assert [rij.maand for rij in einde.maanden] == [12]
    januari = _maand(begin, 1)
    assert januari.status == "gepland"
    assert januari.plusmin == Decimal("-122.00")
    assert januari.cumulatief == Decimal("-122.00")
    assert all(rij.jaar == 2027 for rij in begin.maanden)
    assert begin.regel_voor(1).cumulatief == Decimal("-122.00")


def test_zonder_vast_maandloon_is_er_geen_saldo():
    overzicht = _overzicht(
        [_hulpkracht(), _vast(date(2026, 10, 1))],
        diensten=[_dienst(date(2026, 9, 8), 8 * 60, "hulpkracht")],
    )
    assert [rij.maand for rij in overzicht.maanden] == [10, 11, 12]
    assert overzicht.regel_voor(9) is None


def test_lopende_maand_zonder_diensten_telt_wel_mee():
    overzicht = _overzicht([_vast(date(2026, 10, 1))])
    oktober = _maand(overzicht, 10)
    assert oktober.status == "gepland"
    assert oktober.gewerkt == Decimal("0.00")
    assert oktober.plusmin == Decimal("-130.00")
    assert _maand(overzicht, 11).status == "geen rooster"
    assert overzicht.projectie == Decimal("-130.00")


def test_manus_saldo_blijft_bewaard_zonder_de_ruwe_lijst():
    payload = {
        "selectedPeriod": {
            "id": 4242,
            "fromDate": 46264,
            "toDate": 46293,
            "year": 2026,
            "name": "september 2026",
        },
        "realizedHours": 120 * 60,
        "compensationGained": 0,
        "plusMinusGained": 90,
        "vacationUsed": 0,
        "allowances": 0,
        "balances": [
            {"name": "Verlof", "beginBalance": 1000, "endBalance": 900},
            {
                "name": "Plus/min",
                "beginBalance": {"hours": 0},
                "endBalance": {"hours": 300},
            },
        ],
        "weeks": [{"week": 36, "realizedHours": 2400}],
    }
    opgeslagen = samenvatting_uit(payload)
    assert "balances" not in opgeslagen
    assert "weeks" not in opgeslagen
    assert opgeslagen["manus_begin_minuten"] == 0
    assert opgeslagen["manus_eind_minuten"] == 300
    opslag.bewaar_samenvatting(opgeslagen)
    terug = opslag.alle_samenvattingen()[0]
    assert terug["manus_begin_minuten"] == 0
    assert terug["manus_eind_minuten"] == 300
    assert "balances" not in terug


def test_verlofsaldo_van_mymanus_wordt_niet_het_urensaldo():
    alleen_verlof = samenvatting_uit({
        "selectedPeriod": {"id": 1, "name": "oktober 2026", "fromDate": 46294, "toDate": 46324, "year": 2026},
        "realizedHours": 0,
        "balances": [{"name": "Vakantie", "beginBalance": 100, "endBalance": 80}],
    })
    assert alleen_verlof["manus_begin_minuten"] is None
    assert alleen_verlof["manus_eind_minuten"] is None

    twee_onbekend = samenvatting_uit({
        "selectedPeriod": {"id": 2, "name": "oktober 2026", "fromDate": 46294, "toDate": 46324, "year": 2026},
        "realizedHours": 0,
        "balances": [
            {"name": "verzonnen", "beginBalance": 10, "endBalance": 20},
            {"name": "ook verzonnen", "beginBalance": 30, "endBalance": 40},
        ],
    })
    assert twee_onbekend["manus_eind_minuten"] is None


def test_bestaande_database_krijgt_de_saldo_kolommen():
    with opslag.verbinding() as conn:
        conn.execute("ALTER TABLE periodesamenvatting DROP COLUMN manus_begin_minuten")
        conn.execute("ALTER TABLE periodesamenvatting DROP COLUMN manus_eind_minuten")
    opslag.init_db()
    opslag.bewaar_samenvatting({
        "periode_id": 7,
        "naam": "augustus 2026",
        "van": date(2026, 8, 1),
        "tot": date(2026, 8, 31),
        "jaar": 2026,
        "gerealiseerd_minuten": 60,
        "plusmin_minuten": None,
        "verlof_minuten": 0,
    })
    terug = opslag.alle_samenvattingen()[0]
    assert terug["manus_begin_minuten"] is None
    assert terug["manus_eind_minuten"] is None


def _nu():
    return datetime(2026, 10, 10, 12, 0, tzinfo=AMSTERDAM)


def test_maandscherm_en_saldopagina_tonen_het_jaar(monkeypatch, client):
    import main

    monkeypatch.setattr(main, "nu", _nu)
    opslag.vervang_perioden([{
        **standaard_periode_dicts()[1],
        "geldig_vanaf": "2026-09-01",
        "geldig_tot": "",
        "uren_per_week": "30",
        "uurloon": "15",
        "vast_maandloon": True,
    }])
    opslag.bewaar_samenvatting({
        "periode_id": 9001,
        "naam": "september 2026",
        "van": date(2026, 9, 1),
        "tot": date(2026, 9, 30),
        "jaar": 2026,
        "gerealiseerd_minuten": 120 * 60,
        "compensatie_minuten": 0,
        "plusmin_minuten": 90,
        "verlof_minuten": 10 * 60,
        "toeslagen": 0,
        "manus_begin_minuten": 210,
        "manus_eind_minuten": 300,
    })
    opslag.bewaar_diensten([_dienst(date(2026, 10, 6), 140 * 60, "oktober-pagina")])

    maand = client.get("/?maand=2026-10", headers=INGRESS)
    html = maand.get_data(as_text=True)
    assert maand.status_code == 200
    assert "Saldo dit jaar t/m oktober: <strong>+10,00 uur</strong>" in html
    assert "10,00 uur nog gepland" in html
    assert "Indicatie:" in html
    assert "€ 150,00" in html
    assert "Volgens MyManus: +5,00 uur (t/m september)" in html
    assert "Los van deze telling." in html
    assert 'href="/saldo?jaar=2026"' in html

    saldo = client.get("/saldo?jaar=2026", headers=INGRESS)
    saldo_html = saldo.get_data(as_text=True)
    assert saldo.status_code == 200
    assert "Saldo 2026" in saldo_html
    assert "naar rato" not in saldo_html
    assert "140,00" in saldo_html
    assert "Volgens MyManus:" in saldo_html
    assert "plus/min +1,50" in saldo_html
    assert "saldo +5,00" in saldo_html
    assert "Saldo eind 2026" in saldo_html
    assert "November en december hebben nog geen rooster en zitten niet in dit getal." in saldo_html
    assert (
        "Volgens de cao wordt het saldo uiterlijk eind december verrekend; "
        "vraag je werkgever hoe minuren worden behandeld."
    ) in saldo_html

    volgend = client.get("/saldo?jaar=2027", headers=INGRESS).get_data(as_text=True)
    assert "Saldo 2027" in volgend
    assert "140,00" not in volgend
    assert "geen rooster" in volgend
    assert "Saldo eind 2026" not in volgend

    september = client.get("/?maand=2026-09", headers=INGRESS).get_data(as_text=True)
    assert "Saldo dit jaar t/m september" in september
    assert "uur nog gepland" not in september


def test_deels_begonnen_maand_staat_op_het_saldoscherm(monkeypatch, client):
    import main

    monkeypatch.setattr(main, "nu", _nu)
    opslag.vervang_perioden([{
        **standaard_periode_dicts()[1],
        "geldig_vanaf": "2026-10-15",
        "geldig_tot": "",
        "uren_per_week": "30",
        "uurloon": "15",
        "vast_maandloon": True,
    }])
    opslag.bewaar_diensten([
        _dienst(date(2026, 10, 10), 8 * 60, "ervoor"),
        _dienst(date(2026, 10, 16), 450, "erna"),
    ])
    html = client.get("/saldo?jaar=2026", headers=INGRESS).get_data(as_text=True)
    assert "71,29" in html
    assert "naar rato" in html
    assert "gepland" in html
    maand = client.get("/?maand=2026-10", headers=INGRESS).get_data(as_text=True)
    assert "Saldo dit jaar t/m oktober" in maand
    assert "uur nog gepland" in maand
