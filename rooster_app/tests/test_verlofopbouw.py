"""Verlofopbouw en saldo op een datum, met verzonnen uren.

144 uur per jaar en 1 oktober 2026 zijn de standaard van de add-on, niet
een loonstrook. De tests controleren de formule: per kalenderdag, en
opgenomen min aangevraagd tot de gekozen datum.
"""
import json
import pathlib
from datetime import date
from decimal import Decimal

import opslag
from conftest import INGRESS
from main import _uren
from salaris import periode_uit_dict, rond_uren, standaard_periode_dicts
from verlofopbouw import opbouw_uren, verlofstand

START = date(2026, 10, 1)
JAARUREN = Decimal(144)


def _perioden():
    return [periode_uit_dict(rij) for rij in standaard_periode_dicts()]


def _vrij(van, tot=None, *, aangevraagd=False, minuten=None, gedeeltelijk=False, van_minuten=None, tot_minuten=None):
    return {
        "van": van,
        "tot": tot or van,
        "titel": "Vrij",
        "aangevraagd": aangevraagd,
        "uren_minuten": minuten,
        "gedeeltelijk": gedeeltelijk,
        "van_minuten": van_minuten,
        "tot_minuten": tot_minuten,
    }


def _dienst(dag, start, eind, totaal, uniek=None):
    return {
        "datum": dag,
        "start_minuten": start,
        "eind_minuten": eind,
        "totaal_minuten": totaal,
        "pauze_minuten": 0,
        "uniek": uniek or f"dienst-{dag.isoformat()}-{start}-{eind}@rooster-app",
    }


def _stand(peildatum, verloven=None, diensten=None, perioden=None, start=START, uren=JAARUREN):
    return verlofstand(
        peildatum,
        start=start,
        uren_per_jaar=uren,
        verloven=verloven or [],
        diensten=diensten or [],
        perioden=perioden if perioden is not None else _perioden(),
    )


def test_een_heel_jaar_levert_precies_de_jaaruren_ook_in_een_schrikkeljaar():
    assert opbouw_uren(date(2027, 1, 1), date(2027, 12, 31), JAARUREN) == JAARUREN
    assert opbouw_uren(date(2028, 1, 1), date(2028, 12, 31), JAARUREN) == JAARUREN
    # 1 oktober tot en met 30 september is eveneens één jaar, over de jaargrens.
    assert opbouw_uren(START, date(2027, 9, 30), JAARUREN) == JAARUREN


def test_opbouw_gaat_per_dag_en_een_schrikkeldag_telt_minder():
    assert opbouw_uren(START, date(2026, 9, 30), JAARUREN) == Decimal(0)
    assert opbouw_uren(START, START, JAARUREN) == JAARUREN / Decimal(365)
    # Oktober tot en met december 2026 is 92 dagen.
    assert opbouw_uren(START, date(2026, 12, 31), JAARUREN) == JAARUREN * 92 / Decimal(365)
    schrikkel = opbouw_uren(date(2028, 2, 29), date(2028, 2, 29), JAARUREN)
    gewoon = opbouw_uren(date(2027, 3, 1), date(2027, 3, 1), JAARUREN)
    assert schrikkel == JAARUREN / Decimal(366)
    assert gewoon == JAARUREN / Decimal(365)
    assert schrikkel < gewoon


def test_saldo_op_datum_trekt_goedgekeurd_en_aangevraagd_af():
    """Vandaag trekt alleen opgenomen verlof af. De aanvraag telt pas mee
    op een datum waarop dat verlof valt.
    """
    verloven = [
        _vrij(date(2026, 10, 5), minuten=360),
        _vrij(date(2026, 12, 21), date(2026, 12, 24), aangevraagd=True),
    ]
    vandaag = _stand(date(2026, 10, 12), verloven)
    assert vandaag.opgebouwd == rond_uren(JAARUREN * 12 / Decimal(365))
    assert vandaag.opgenomen == Decimal("6.00")
    assert vandaag.aangevraagd == Decimal("0.00")
    assert vandaag.openstaand == Decimal("24.00")
    assert vandaag.saldo == rond_uren(vandaag.opgebouwd - Decimal("6.00"))
    assert vandaag.saldo < 0
    assert vandaag.verwacht == vandaag.saldo

    einde = _stand(date(2026, 12, 31), verloven)
    assert einde.opgebouwd == rond_uren(JAARUREN * 92 / Decimal(365))
    assert einde.opgenomen == Decimal("6.00")
    assert einde.aangevraagd == Decimal("24.00")
    assert einde.verwacht == rond_uren(einde.opgebouwd - Decimal("6") - Decimal("24"))
    assert einde.verwacht > 0


def test_goedgekeurd_verlof_na_vandaag_gaat_er_nog_niet_af():
    verloven = [_vrij(date(2026, 12, 14))]
    vandaag = _stand(date(2026, 10, 12), verloven)
    assert vandaag.opgenomen == Decimal("0.00")
    assert vandaag.goedgekeurd_later == Decimal("6.00")
    einde = _stand(date(2026, 12, 31), verloven)
    assert einde.opgenomen == Decimal("6.00")
    assert einde.goedgekeurd_later == Decimal("0.00")


def test_verlof_voor_de_startdatum_telt_niet_mee():
    # 30 september valt nog in de all-in periode. Alleen 1 en 2 oktober tellen.
    stand = _stand(date(2026, 10, 2), [_vrij(date(2026, 9, 30), date(2026, 10, 2))])
    assert stand.opgenomen == Decimal("12.00")


def test_uren_uit_mymanus_gaan_voor_de_schatting_en_splitsen_over_de_reeks():
    # Drie gelijke werkdagen, peildatum op de tweede. 18 uur uit MyManus.
    stand = _stand(
        date(2026, 10, 6),
        [_vrij(date(2026, 10, 5), date(2026, 10, 7), minuten=18 * 60)],
    )
    assert stand.opgenomen == Decimal("12.00")
    assert stand.regels[0].uren == Decimal("18.00")
    assert stand.regels[0].meegeteld == Decimal("12.00")
    assert stand.regels[0].geschat is False


def test_mymanus_uren_over_de_startdatum_alleen_het_deel_erna():
    # 2,4 + 6 + 6 = 14,4. Het aandeel van oktober is 12 uur.
    stand = _stand(
        date(2026, 10, 2),
        [_vrij(date(2026, 9, 30), date(2026, 10, 2), minuten=Decimal("864"))],
    )
    assert stand.opgenomen == Decimal("12.00")


def test_zonder_uren_geldt_de_dienst_en_anders_een_vijfde_van_het_contract():
    dag = date(2026, 10, 6)
    met_dienst = _stand(dag, [_vrij(dag)], [_dienst(dag, 13 * 60, 21 * 60, 450)])
    assert met_dienst.opgenomen == Decimal("7.50")

    # Dezelfde kloktijd twee keer is één dienst. Anders wordt het verlof het dubbele.
    dubbel = _stand(dag, [_vrij(dag)], [
        _dienst(dag, 13 * 60, 21 * 60, 450, uniek="dienst-oud@rooster-app"),
        _dienst(dag, 13 * 60, 21 * 60, 450, uniek="dienst-id-9@rooster-app"),
    ])
    assert dubbel.opgenomen == Decimal("7.50")

    zonder = _stand(dag, [_vrij(dag)])
    assert zonder.opgenomen == Decimal("6.00")
    assert zonder.regels[0].geschat is True


def test_deel_van_de_dag_is_het_overlappende_stuk_van_de_dienst():
    dag = date(2026, 10, 6)
    # 18:00 tot het eind van de dienst om 21:00, pauze naar rato van 450/480.
    stand = _stand(
        dag,
        [_vrij(dag, gedeeltelijk=True, van_minuten=18 * 60, tot_minuten=23 * 60 + 59)],
        [_dienst(dag, 13 * 60, 21 * 60, 450)],
    )
    assert stand.opgenomen == rond_uren(Decimal(450) * Decimal(180) / Decimal(480) / Decimal(60))

    # Zonder dienst blijft het de klokduur, niet meer dan een contractdag.
    kaal = _stand(
        dag,
        [_vrij(dag, gedeeltelijk=True, van_minuten=18 * 60, tot_minuten=23 * 60 + 59)],
    )
    assert kaal.opgenomen == rond_uren(Decimal(359) / Decimal(60))


def test_weekend_zonder_dienst_telt_niet():
    stand = _stand(date(2026, 10, 12), [_vrij(date(2026, 10, 10), date(2026, 10, 11))])
    assert stand.opgenomen == Decimal("0.00")
    assert stand.regels == ()


def test_zonder_contract_en_zonder_dienst_is_een_dag_nul():
    stand = _stand(date(2026, 10, 5), [_vrij(date(2026, 10, 5))], perioden=[])
    assert stand.opgenomen == Decimal("0.00")


def test_opties_vervangen_de_standaard_en_ongeldig_valt_terug():
    assert opslag.verlof_opbouw_uren() == Decimal("144")
    assert opslag.verlof_vanaf() == START
    pad = pathlib.Path(opslag.DATA_DIR) / "options.json"
    pad.write_text(json.dumps({"verlof_opbouw_uren": "100,5", "verlof_vanaf": "2027-03-01"}), encoding="utf-8")
    assert opslag.verlof_opbouw_uren() == Decimal("100.5")
    assert opslag.verlof_vanaf() == date(2027, 3, 1)
    pad.write_text(json.dumps({"verlof_opbouw_uren": "geen", "verlof_vanaf": "morgen"}), encoding="utf-8")
    assert opslag.verlof_opbouw_uren() == Decimal("144")
    assert opslag.verlof_vanaf() == START
    pad.write_text(json.dumps({"verlof_opbouw_uren": -5}), encoding="utf-8")
    assert opslag.verlof_opbouw_uren() == Decimal("144")


def test_bestaande_verloftabel_krijgt_een_kolom_voor_de_uren():
    with opslag.verbinding() as conn:
        conn.execute("ALTER TABLE verlof DROP COLUMN uren_minuten")
    try:
        opslag.init_db()
        with opslag.verbinding() as conn:
            kolommen = {rij[1] for rij in conn.execute("PRAGMA table_info(verlof)")}
        assert "uren_minuten" in kolommen
    finally:
        opslag.init_db()


def test_configuratie_noemt_de_verlofopties_en_de_versie():
    tekst = pathlib.Path(__file__).resolve().parents[2].joinpath("rooster_app", "config.yaml").read_text(encoding="utf-8")
    assert 'verlof_opbouw_uren: 144.0' in tekst
    assert 'verlof_vanaf: "2026-10-01"' in tekst
    assert "float(0,1000)" in tekst


def _pagina(client, query=""):
    return client.get(f"/verlof{query}", headers=INGRESS).get_data(as_text=True)


def test_verlofpagina_toont_negatief_saldo_en_saldo_op_datum(client, monkeypatch):
    monkeypatch.setattr("main.vandaag", lambda: date(2026, 10, 12))
    opslag.vervang_verlof_van_jaren([2026], [
        {
            "van": date(2026, 10, 5),
            "tot": date(2026, 10, 5),
            "code": "V",
            "omschrijving": "",
            "uniek": "verlof-id-5@rooster-app",
            "aangevraagd": False,
            "uren_minuten": 360,
        },
        {
            "van": date(2026, 12, 21),
            "tot": date(2026, 12, 24),
            "code": "V",
            "omschrijving": "",
            "uniek": "verlof-id-21@rooster-app",
            "aangevraagd": True,
        },
    ])
    nu = _stand(date(2026, 10, 12), [
        _vrij(date(2026, 10, 5), minuten=360),
        _vrij(date(2026, 12, 21), date(2026, 12, 24), aangevraagd=True),
    ])
    html = _pagina(client)
    assert "Saldo op datum" in html
    assert 'name="op"' in html
    assert "in de min" in html
    assert "negatief" in html
    assert _uren(nu.saldo) in html
    assert "uit MyManus" in html
    assert "geschat" in html
    assert "telt nog niet mee" in html
    assert 'href="/verlof"' in html

    einde = _stand(date(2026, 12, 31), [
        _vrij(date(2026, 10, 5), minuten=360),
        _vrij(date(2026, 12, 21), date(2026, 12, 24), aangevraagd=True),
    ])
    later = _pagina(client, "?op=2026-12-31")
    assert f"{_uren(einde.verwacht)} uur" in later
    assert "telt nog niet mee" not in later
    assert "inclusief aangevraagd verlof tot die datum" in later

    maand = client.get("/", headers=INGRESS).get_data(as_text=True)
    assert "Het verlofsaldo" in maand


def test_verlofpagina_gebruikt_de_add_on_opties(client, monkeypatch):
    monkeypatch.setattr("main.vandaag", lambda: date(2027, 4, 1))
    pad = pathlib.Path(opslag.DATA_DIR) / "options.json"
    pad.write_text(
        json.dumps({"verlof_opbouw_uren": 100, "verlof_vanaf": "2027-03-01"}),
        encoding="utf-8",
    )
    html = _pagina(client)
    assert "Opbouw is 100 uur per kalenderjaar, per dag, vanaf 1 maart 2027." in html


def test_verlof_zonder_ingress_blijft_dicht(client):
    assert client.get("/verlof").status_code == 403
