"""Salarisregels met verzonnen uren en een verzonnen uurloon.

De tests controleren de opbouw (uren × loon, toeslag, flexverlof, 8%
vakantiegeld, pensioen na de eigen premie), niet de bedragen van een
echte loonstrook. Het uurloon in de app blijft leeg tot je het zelf invult.
"""
from datetime import date
from decimal import Decimal

from salaris import (
    contracturen_per_maand,
    deel_uit_uren,
    geld,
    loonheffing_maand,
    mei_waarin_vakantiegeld_valt,
    periode_op,
    rond_uren,
    standaard_periode_dicts,
    tabellen_voor,
    toeslag_specificatie,
    uurloon_van,
)


def _periode(**wijzigingen):
    from salaris import Periode

    basis = dict(
        naam="Test",
        geldig_vanaf=date(2020, 1, 1),
        geldig_tot=None,
        uren_per_week=Decimal("38"),
        uurloon=Decimal("10"),
        all_in=True,
        flex_verlof_percentage=Decimal("10"),
        vakantiegeld_percentage=Decimal("8"),
        vakantiegeld_maandelijks=True,
        vast_maandloon=False,
        pensioen_percentage=Decimal("0"),
        jaarfranchise=Decimal("0"),
        fulltime_uren_per_week=Decimal("38"),
        wga_percentage=Decimal("0"),
        avond_vanaf=18 * 60,
        avond_percentage=Decimal("50"),
        zondag_percentage=Decimal("50"),
        zaterdag_percentage=Decimal("0"),
    )
    basis.update(wijzigingen)
    return Periode(**basis)


def test_all_in_volgt_de_formule_uren_maal_loon():
    periode = _periode(geldig_tot=date(2026, 9, 30))
    uren = Decimal("40")
    toeslag_uren = Decimal("8")
    deel = deel_uit_uren(
        2026, 9, uren, [(toeslag_uren, Decimal("50"))],
        periode, [periode],
    )
    assert deel.salaris == geld(uren * periode.uurloon)
    assert deel.toeslag_bedrag == geld(toeslag_uren * periode.uurloon * Decimal("0.5"))
    assert deel.flex_uren == rond_uren(uren * periode.flex_verlof_percentage / Decimal(100))
    assert deel.flex_bedrag == geld(deel.flex_uren * periode.uurloon)
    assert deel.vakantiegeld == geld((deel.salaris + deel.flex_bedrag) * Decimal("0.08"))
    assert deel.vakantiegeld_opbouw == Decimal("0")
    assert deel.bruto == deel.salaris + deel.toeslag_bedrag + deel.flex_bedrag + deel.vakantiegeld
    assert deel.werk_maand == 9
    assert deel.loonheffing == loonheffing_maand(deel.sv_loon, 2026)
    assert deel.netto == geld(deel.sv_loon - deel.wga - deel.loonheffing)
    assert deel.pensioen == Decimal("0")
    assert deel.sv_loon == deel.bruto


def test_pensioen_is_het_percentage_over_bruto_na_de_eigen_premie():
    periode = _periode(pensioen_percentage=Decimal("10"), jaarfranchise=Decimal("0"))
    deel = deel_uit_uren(2026, 9, Decimal("40"), [], periode, [periode])
    # 40 × 10, plus 10% flexverlof, plus 8% vakantiegeld daarover = 475,20.
    # premie = 10/110 × dat bruto.
    assert deel.bruto == Decimal("475.20")
    assert deel.pensioen == Decimal("43.20")
    assert deel.sv_loon == Decimal("432.00")


def test_wga_premie_is_sv_loon_maal_percentage_op_centen():
    # 1000,00 × 0,808% = 8,08. De heffing blijft over het hele sv-loon.
    periode = _periode(
        wga_percentage=Decimal("0.808"),
        pensioen_percentage=Decimal("0"),
        all_in=False,
        vakantiegeld_maandelijks=False,
        vast_maandloon=False,
        flex_verlof_percentage=Decimal("0"),
        vakantiegeld_percentage=Decimal("0"),
        uurloon=Decimal("10"),
    )
    deel = deel_uit_uren(2026, 10, Decimal("100"), [], periode, [periode])
    assert deel.bruto == Decimal("1000.00")
    assert deel.sv_loon == Decimal("1000.00")
    assert deel.wga == Decimal("8.08")
    assert deel.wga == geld(deel.sv_loon * Decimal("0.808") / Decimal(100))
    assert deel.loonheffing == loonheffing_maand(deel.sv_loon, 2026)
    assert deel.netto == geld(deel.sv_loon - deel.wga - deel.loonheffing)
    # 1,00 × 0,808% = 0,00808, afgerond op een cent naar boven.
    klein = _periode(
        wga_percentage=Decimal("0.808"),
        all_in=False,
        vakantiegeld_maandelijks=False,
        flex_verlof_percentage=Decimal("0"),
        vakantiegeld_percentage=Decimal("0"),
        uurloon=Decimal("1"),
    )
    deel_klein = deel_uit_uren(2026, 10, Decimal("1"), [], klein, [klein])
    assert deel_klein.sv_loon == Decimal("1.00")
    assert deel_klein.wga == Decimal("0.01")


def test_loonheffing_volgt_de_witte_maandtabel():
    # Publieke regels uit de witte maandtabel 2026, mét loonheffingskorting.
    assert loonheffing_maand(Decimal("1476.00"), 2026) == Decimal("36.50")
    assert loonheffing_maand(Decimal("1480.49"), 2026) == Decimal("36.50")
    assert loonheffing_maand(Decimal("1588.50"), 2026) == Decimal("41.83")
    assert loonheffing_maand(Decimal("1593.00"), 2026) == Decimal("42.00")
    assert loonheffing_maand(Decimal("4.49"), 2026) == Decimal("0.00")
    assert loonheffing_maand(Decimal("0"), 2026) == Decimal("0")
    periode = _periode()
    deel = deel_uit_uren(2026, 9, Decimal("40"), [], periode, [periode])
    assert deel.loonheffing == loonheffing_maand(deel.sv_loon, 2026)
    assert deel.netto == geld(deel.sv_loon - deel.wga - deel.loonheffing)
    assert deel.tabellen_jaar == 2026


def test_onbekend_jaar_gebruikt_de_laatste_tabel():
    gebruikt, _tabel = tabellen_voor(2031)
    assert gebruikt == 2026
    assert loonheffing_maand(Decimal("2000"), 2031) == loonheffing_maand(Decimal("2000"), 2026)


def test_oktober_rekent_alleen_de_oktoberuren():
    oud = _periode(naam="Hulpkracht", geldig_tot=date(2026, 9, 30), all_in=True)
    nieuw = _periode(
        naam="Parttime",
        geldig_vanaf=date(2026, 10, 1),
        geldig_tot=None,
        uurloon=None,
        all_in=False,
        vakantiegeld_maandelijks=False,
        vast_maandloon=True,
        uren_per_week=Decimal("30"),
    )
    perioden = [oud, nieuw]
    september = deel_uit_uren(
        2026, 9, Decimal("40"), [(Decimal("8"), Decimal("50"))],
        oud, perioden,
    )
    oktober = deel_uit_uren(
        2026, 10, Decimal("100"), [(Decimal("4"), Decimal("50"))],
        nieuw, perioden,
    )
    assert oktober.uurloon == Decimal("10")
    assert oktober.vast_maandloon
    assert oktober.contracturen == Decimal("130.00")
    assert oktober.salaris == Decimal("1300.00")
    assert oktober.extra_uren == Decimal("0")
    assert oktober.plusmin == Decimal("-30.00")
    assert oktober.flex_bedrag == Decimal("0")
    assert oktober.vakantiegeld == Decimal("0")
    assert oktober.vakantiegeld_opbouw == geld(oktober.salaris * Decimal("0.08"))
    assert oktober.bruto == oktober.salaris + oktober.toeslag_bedrag
    assert september.werk_maand == 9 and oktober.werk_maand == 10
    assert september.loonheffing == loonheffing_maand(september.sv_loon, 2026)
    assert oktober.loonheffing == loonheffing_maand(oktober.sv_loon, 2026)
    assert september.netto == geld(september.sv_loon - september.wga - september.loonheffing)
    assert oktober.netto == geld(oktober.sv_loon - oktober.wga - oktober.loonheffing)
    # Eén tabel over de som zou een ander bedrag geven. Elke maand houdt de zijne.
    samen = loonheffing_maand(september.sv_loon + oktober.sv_loon, 2026)
    assert oktober.loonheffing != samen
    assert september.loonheffing + oktober.loonheffing != samen


def test_lege_periode_erft_het_uurloon_van_de_vorige():
    oud = _periode(geldig_tot=date(2026, 9, 30), uurloon=Decimal("15"))
    nieuw = _periode(geldig_vanaf=date(2026, 10, 1), uurloon=None, naam="Later")
    assert uurloon_van([oud, nieuw], nieuw) == Decimal("15")
    assert uurloon_van([oud, nieuw], oud) == Decimal("15")


def test_zonder_enig_uurloon_blijft_het_bedrag_leeg():
    periode = _periode(uurloon=None)
    deel = deel_uit_uren(2026, 10, Decimal("10"), [], periode, [periode])
    assert deel.onvolledig
    assert deel.bruto == 0
    assert deel.uren == Decimal("10.00")


def test_contracturen_zijn_weekuren_maal_52_gedeeld_door_12():
    assert contracturen_per_maand(_periode(uren_per_week=Decimal("30"))) == Decimal("130.00")
    assert contracturen_per_maand(_periode(uren_per_week=Decimal("12"))) == Decimal("52.00")


def test_vast_maandloon_betaalt_het_contract_en_uren_erboven():
    periode = _periode(
        vast_maandloon=True,
        all_in=False,
        vakantiegeld_maandelijks=False,
        uren_per_week=Decimal("30"),
        uurloon=Decimal("10"),
    )
    onder = deel_uit_uren(2026, 10, Decimal("100"), [], periode, [periode], verlof_uren=Decimal("30"))
    assert onder.salaris == Decimal("1300.00")
    assert onder.extra_uren == Decimal("0")
    assert onder.plusmin == Decimal("0.00")
    assert onder.vakantiegeld_opbouw == Decimal("104.00")

    boven = deel_uit_uren(2026, 10, Decimal("110"), [], periode, [periode], verlof_uren=Decimal("30"))
    assert boven.extra_uren == Decimal("10.00")
    assert boven.basis_bedrag == Decimal("1300.00")
    assert boven.salaris == Decimal("1400.00")
    assert boven.plusmin == Decimal("10.00")


def test_opgebouwd_vakantiegeld_zit_niet_in_het_netto():
    from overzicht import vakantiegeld_open

    periode = _periode(
        geldig_vanaf=date(2026, 10, 1),
        uurloon=Decimal("10"),
        all_in=False,
        vakantiegeld_maandelijks=False,
        vast_maandloon=False,
        uren_per_week=Decimal("30"),
    )
    delen = [
        deel_uit_uren(jaar, maand, Decimal("100"), [], periode, [periode])
        for jaar, maand in (
            (2026, 10), (2026, 11), (2026, 12),
            (2027, 1), (2027, 2), (2027, 3), (2027, 4), (2027, 5),
        )
    ]
    april = next(deel for deel in delen if (deel.werk_jaar, deel.werk_maand) == (2027, 4))
    mei = next(deel for deel in delen if (deel.werk_jaar, deel.werk_maand) == (2027, 5))
    assert mei.vakantiegeld == 0
    assert mei.vakantiegeld_opbouw == geld(mei.salaris * Decimal("0.08"))
    assert mei.bruto == april.bruto == mei.salaris
    assert mei.loonheffing == loonheffing_maand(mei.sv_loon, 2027)
    assert mei.netto == april.netto
    assert mei.tabellen_jaar == 2026
    opbouw = geld(sum((deel.vakantiegeld_opbouw for deel in delen), Decimal(0)))
    assert opbouw == Decimal("640.00")
    assert vakantiegeld_open(delen, date(2027, 4, 30)) == opbouw
    assert vakantiegeld_open(delen, date(2027, 5, 1)) == Decimal("0")
    assert mei_waarin_vakantiegeld_valt(2026, 10) == (2027, 5)
    assert mei_waarin_vakantiegeld_valt(2027, 1) == (2027, 5)


def test_toeslag_volgt_de_vensters_van_de_cao():
    from salaris import periode_uit_dict

    periode = periode_uit_dict(standaard_periode_dicts()[0])
    periode = _periode(
        avond_vanaf=periode.avond_vanaf,
        nacht_tot=periode.nacht_tot,
        nacht_percentage=periode.nacht_percentage,
        zaterdag_vanaf=periode.zaterdag_vanaf,
        zaterdag_percentage=periode.zaterdag_percentage,
        feestdag_percentage=periode.feestdag_percentage,
    )
    # Dinsdag tot 21:00 is nog geen avond. Vanaf 21:00 wel.
    assert toeslag_specificatie(date(2026, 10, 6), 13 * 60, 21 * 60, [], periode) == []
    assert toeslag_specificatie(date(2026, 10, 6), 21 * 60, 23 * 60, [], periode) == [
        (Decimal("2.00"), Decimal("50"))
    ]
    # Maandag 02:00–05:00 is nacht, zondag 02:00–05:00 is de zondagregel.
    assert toeslag_specificatie(date(2026, 10, 5), 2 * 60, 5 * 60, [], periode) == [
        (Decimal("3.00"), Decimal("50"))
    ]
    zondag_nacht = _periode(
        nacht_percentage=Decimal("0"),
        zondag_percentage=Decimal("50"),
        avond_vanaf=21 * 60,
    )
    assert toeslag_specificatie(date(2026, 10, 11), 2 * 60, 5 * 60, [], zondag_nacht) == [
        (Decimal("3.00"), Decimal("50"))
    ]
    # Zondag 11 oktober, 09:00–18:00 met een uur pauze.
    zondag = toeslag_specificatie(
        date(2026, 10, 11), 9 * 60, 18 * 60, [(12 * 60, 13 * 60)], periode,
    )
    assert zondag == [(Decimal("8.00"), Decimal("50"))]
    # 2e paasdag 2026 is maandag 6 april. De feestdag vervangt de 0% van een gewone maandag.
    feestdag = toeslag_specificatie(date(2026, 4, 6), 10 * 60, 16 * 60, [], periode)
    assert feestdag == [(Decimal("6.00"), Decimal("100"))]


def test_verlofdagen_tellen_als_een_vijfde_van_de_week():
    from overzicht import verlofuren_in_maand

    periode = _periode(uren_per_week=Decimal("30"))
    # 4 en 5 november 2026 zijn woensdag en donderdag: twee werkdagen.
    uren = verlofuren_in_maand(
        [{"van": date(2026, 11, 4), "tot": date(2026, 11, 5)}],
        2026, 11, periode,
    )
    assert uren == Decimal("12.00")
    weekend = verlofuren_in_maand(
        [{"van": date(2026, 11, 7), "tot": date(2026, 11, 8)}],
        2026, 11, periode,
    )
    assert weekend == Decimal("0")


def test_zondag_telt_de_hele_dag_en_niet_ook_de_avond():
    periode = _periode(avond_percentage=Decimal("75"), avond_vanaf=21 * 60)
    uit = toeslag_specificatie(date(2026, 10, 11), 16 * 60, 22 * 60, [], periode)
    assert uit == [(Decimal("6.00"), Decimal("50"))]


def test_zaterdag_geldt_vanaf_achttien_uur():
    periode = _periode(zaterdag_percentage=Decimal("50"), zaterdag_vanaf=18 * 60, avond_vanaf=21 * 60)
    assert toeslag_specificatie(date(2026, 10, 10), 9 * 60, 17 * 60, [], periode) == []
    assert toeslag_specificatie(date(2026, 10, 10), 18 * 60, 22 * 60, [], periode) == [
        (Decimal("4.00"), Decimal("50"))
    ]
    zonder = _periode(zaterdag_percentage=Decimal("0"), zaterdag_vanaf=18 * 60, nacht_percentage=Decimal("50"))
    assert toeslag_specificatie(date(2026, 10, 10), 18 * 60, 22 * 60, [], zonder) == []
    assert toeslag_specificatie(date(2026, 10, 10), 0, 2 * 60, [], zonder) == [
        (Decimal("2.00"), Decimal("50"))
    ]


def test_nachtdienst_krijgt_na_middernacht_de_volgende_dag():
    periode = _periode(avond_vanaf=21 * 60, nacht_percentage=Decimal("50"), zaterdag_percentage=Decimal("50"))
    # Vrijdag 22:00 tot zaterdag 02:00: avond én nachttarief, allebei 50%.
    uit = toeslag_specificatie(date(2026, 10, 9), 22 * 60, 2 * 60, [], periode)
    assert uit == [(Decimal("4.00"), Decimal("50"))]


def test_standaardperioden_dekken_de_contractwisseling():
    from salaris import periode_uit_dict

    perioden = [periode_uit_dict(rij) for rij in standaard_periode_dicts()]
    september = periode_op(perioden, date(2026, 9, 30))
    oktober = periode_op(perioden, date(2026, 10, 1))
    assert september.naam == "Hulpkracht"
    assert september.all_in and september.vakantiegeld_maandelijks
    assert oktober.naam == "Parttime verkoopmedewerker"
    assert not oktober.all_in and not oktober.vakantiegeld_maandelijks
    assert oktober.uren_per_week == Decimal("30")
    assert oktober.vast_maandloon and not september.vast_maandloon
    assert september.uurloon is None and oktober.uurloon is None
    assert september.wga_percentage == Decimal("0.808")
    assert oktober.wga_percentage == Decimal("0.808")
    assert september.flex_verlof_percentage == Decimal("9.2308")
    assert oktober.avond_vanaf == 21 * 60
    assert oktober.zaterdag_vanaf == 18 * 60
    assert oktober.feestdag_percentage == Decimal("100")
    assert oktober.overwerk is True


def test_bijzondere_beloning_rondt_naar_beneden_af():
    from salaris import heffing_bijzonder, percentage_bijzonder

    assert percentage_bijzonder(Decimal("0"), 2026) == Decimal("0")
    assert percentage_bijzonder(Decimal("11358"), 2026) == Decimal("27.43")
    assert percentage_bijzonder(Decimal("29736"), 2026) == Decimal("33.80")
    assert percentage_bijzonder(Decimal("29737"), 2026) == Decimal("40.20")
    assert percentage_bijzonder(Decimal("200000"), 2026) == Decimal("49.50")
    # 10,05 × 40,20% = 4,0401, naar beneden 4,04.
    assert heffing_bijzonder(Decimal("10.05"), Decimal("30000"), 2026) == Decimal("4.04")
    assert percentage_bijzonder(Decimal("30000"), 2031) == percentage_bijzonder(Decimal("30000"), 2026)


def test_opgebouwde_heffing_zit_niet_in_het_netto():
    from salaris import heffing_bijzonder

    periode = _periode(
        all_in=False,
        vakantiegeld_maandelijks=False,
        vast_maandloon=False,
        flex_verlof_percentage=Decimal("0"),
    )
    deel = deel_uit_uren(2026, 10, Decimal("100"), [], periode, [periode])
    assert deel.heffing_opbouw == heffing_bijzonder(deel.vakantiegeld_opbouw, deel.sv_loon * 12, 2026)
    assert deel.netto == geld(deel.sv_loon - deel.wga - deel.loonheffing)
    assert deel.vakantiegeld == 0


def test_fulltime_franchise_is_18680_gedeeld_door_twaalf():
    from salaris import STANDAARD_JAARFRANCHISE

    assert geld(STANDAARD_JAARFRANCHISE / 12) == Decimal("1556.67")
    periode = _periode(
        pensioen_percentage=Decimal("6.1875"),
        jaarfranchise=Decimal("18680"),
        fulltime_uren_per_week=Decimal("38"),
        uren_per_week=Decimal("38"),
        vast_maandloon=True,
        all_in=False,
        vakantiegeld_maandelijks=False,
        flex_verlof_percentage=Decimal("0"),
        uurloon=Decimal("15"),
    )
    deel = deel_uit_uren(2026, 10, Decimal("160"), [], periode, [periode])
    assert deel.franchise == Decimal("1556.67")
    # Onder de franchise blijft de premie nul.
    klein = _periode(
        pensioen_percentage=Decimal("6.1875"),
        jaarfranchise=Decimal("18680"),
        fulltime_uren_per_week=Decimal("38"),
        uren_per_week=Decimal("4"),
        all_in=False,
        vakantiegeld_maandelijks=False,
        flex_verlof_percentage=Decimal("0"),
        uurloon=Decimal("5"),
    )
    leeg = deel_uit_uren(2026, 10, Decimal("1"), [], klein, [klein])
    assert leeg.pensioen == 0
    assert leeg.grondslag == 0


def test_overwerktoeslag_zit_in_bruto_niet_in_vakantiegeld():
    periode = _periode(all_in=False, vakantiegeld_maandelijks=False, vast_maandloon=False, flex_verlof_percentage=Decimal("0"))
    zonder = deel_uit_uren(2026, 10, Decimal("40"), [], periode, [periode])
    met = deel_uit_uren(
        2026, 10, Decimal("40"), [], periode, [periode],
        overwerk_uren=(Decimal("2"), Decimal("1")),
    )
    assert met.overwerk_125_bedrag == Decimal("5.00")
    assert met.overwerk_150_bedrag == Decimal("5.00")
    assert met.overwerk_bedrag == Decimal("10.00")
    assert met.vakantiegeld_opbouw == zonder.vakantiegeld_opbouw
    assert met.bruto == zonder.bruto + Decimal("10.00")


def _dienst(dag, uren, start=8 * 60):
    return _dienst_minuten(dag, int(uren * 60), start)


def _dienst_minuten(dag, minuten, start=8 * 60):
    return {
        "datum": dag,
        "start_minuten": start,
        "eind_minuten": start + minuten,
        "pauzes": [],
        "totaal_minuten": minuten,
    }


def test_overwerk_per_dag_en_over_vier_weken():
    from datetime import timedelta

    from salaris import overwerk_uit_diensten

    periode = _periode(geldig_vanaf=date(2026, 1, 1))
    # Eén dag van 12 uur, zonder vier weken eromheen: 2 uur à 125% en 1 uur à 150%.
    dag = overwerk_uit_diensten([_dienst(date(2026, 10, 6), 12)], periode, 2026, 10)
    assert dag == (Decimal("2.00"), Decimal("1.00"))
    uit = _periode(overwerk=False)
    assert overwerk_uit_diensten([_dienst(date(2026, 10, 6), 12)], uit, 2026, 10) == (
        Decimal("0.00"),
        Decimal("0.00"),
    )
    # Dienst over middernacht splitst vóór de 9-uursgrens.
    # Vrijdag 12:00 tot zaterdag 08:00 is 12 uur op vrijdag en 8 op zaterdag.
    nacht = {
        "datum": date(2026, 10, 9),
        "start_minuten": 12 * 60,
        "eind_minuten": 8 * 60,
        "pauzes": [],
        "totaal_minuten": 20 * 60,
    }
    assert overwerk_uit_diensten([nacht], periode, 2026, 10) == (Decimal("2.00"), Decimal("1.00"))

    def weken(minuten_per_week, dagen):
        diensten = []
        maandag = date(2026, 10, 5)
        for nummer, minuten in enumerate(minuten_per_week):
            per_dag = minuten // dagen
            for dag_nummer in range(dagen):
                diensten.append(
                    _dienst_minuten(maandag + timedelta(weeks=nummer, days=dag_nummer), per_dag)
                )
        return diensten

    # Minuten, zodat een uur niet via een zwevende komma een minuut kwijtraakt.
    vier_keer_42 = overwerk_uit_diensten(weken([42 * 60] * 4, 5), periode, 2026, 10)
    assert vier_keer_42 == (Decimal("8.00"), Decimal("0.00"))
    assert overwerk_uit_diensten(weken([50 * 60, 30 * 60, 30 * 60, 30 * 60], 6), periode, 2026, 10) == (
        Decimal("0.00"),
        Decimal("0.00"),
    )
    assert overwerk_uit_diensten(weken([50 * 60, 40 * 60, 40 * 60, 40 * 60], 6), periode, 2026, 10) == (
        Decimal("2.00"),
        Decimal("8.00"),
    )
    # Vijf weken van 42 uur. De vijfde week valt in november. Samen 10 uur,
    # niet 14: overlappende vensters tellen het maximum.
    blok = weken([42 * 60] * 5, 5)
    oktober = overwerk_uit_diensten(blok, periode, 2026, 10)
    november = overwerk_uit_diensten(blok, periode, 2026, 11)
    assert oktober == (Decimal("8.00"), Decimal("0.00"))
    assert november == (Decimal("2.00"), Decimal("0.00"))


def test_maand_van_125_50_uur_op_30_uur_heeft_geen_overwerk():
    """Een realistische parttime maand blijft onder de cao-grens.

    125,50 uur op een contract van 30 uur per week is minder dan de 130
    contracturen. Geen dag komt boven 9 uur, geen week boven 40. Extra uren
    zijn het stuk boven het maandcontract; overwerk is alleen de toeslag
    boven 9 uur op een dag of gemiddeld 40 uur over 4 weken. Die twee
    kunnen naast elkaar staan, maar in deze maand zijn ze allebei nul.
    Dubbele rijen van dezelfde kloktijd mogen daar geen overwerk van maken:
    een dag van 7 uur die twee keer meetelt, komt boven de 9 uur uit.
    """
    from overzicht import delen_van_maand

    periode = _periode(
        uren_per_week=Decimal("30"),
        vast_maandloon=True,
        all_in=False,
        vakantiegeld_maandelijks=False,
        flex_verlof_percentage=Decimal("0"),
        pensioen_percentage=Decimal("0"),
        uurloon=Decimal("12"),
    )
    diensten = []
    # 16 dagen van 7 uur en 2 van 6,75 uur. Samen 125,50. Per week hooguit 35.
    dagen = [
        date(2026, 10, 1), date(2026, 10, 2),
        date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7),
        date(2026, 10, 8), date(2026, 10, 9),
        date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14),
        date(2026, 10, 15), date(2026, 10, 16),
        date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21),
        date(2026, 10, 22),
    ]
    for dag in dagen:
        diensten.append(_dienst(dag, 7))
    diensten.append(_dienst_minuten(date(2026, 10, 26), 405))
    diensten.append(_dienst_minuten(date(2026, 10, 27), 405))
    for dienst in diensten:
        dienst["uniek"] = f"dienst-{dienst['datum'].isoformat()}-id-1@rooster-app"
    assert sum(dienst["totaal_minuten"] for dienst in diensten) == 125 * 60 + 30
    deel = delen_van_maand(2026, 10, diensten, [], [periode], [])[0]
    assert deel.uren == Decimal("125.50")
    assert deel.gewerkte_dagen == 18
    assert deel.extra_uren == Decimal("0.00")
    assert deel.plusmin == Decimal("-4.50")
    assert deel.overwerk_125_uren == Decimal("0.00")
    assert deel.overwerk_150_uren == Decimal("0.00")

    dubbel = list(diensten)
    for dienst in diensten:
        kopie = dict(dienst)
        kopie["uniek"] = (
            f"dienst-{dienst['datum'].isoformat()}-"
            f"{dienst['start_minuten']}-{dienst['eind_minuten']}-3@rooster-app"
        )
        dubbel.append(kopie)
    nog = delen_van_maand(2026, 10, dubbel, [], [periode], [])[0]
    assert nog.uren == Decimal("125.50")
    assert nog.gewerkte_dagen == 18
    assert nog.overwerk_125_uren == Decimal("0.00")
    assert nog.overwerk_150_uren == Decimal("0.00")


def test_loonschaal_gaat_voor_een_eerder_uurloon_en_een_ingevuld_loon_wint():
    from salaris import cao_uurloon

    geboren = date(2006, 10, 20)
    assert cao_uurloon(geboren, "2", 2026, 9) == Decimal("9.18")
    assert cao_uurloon(geboren, "2", 2026, 10) == Decimal("12.24")
    assert cao_uurloon(date(2006, 1, 1), "1", 2026, 6) == Decimal("11.99")
    assert cao_uurloon(date(2007, 6, 1), "1", 2026, 6) == Decimal("8.99")
    assert cao_uurloon(date(2005, 6, 1), "1", 2026, 8) == Decimal("14.99")
    assert cao_uurloon(date(2004, 3, 1), "2", 2026, 2) == Decimal("15.30")
    assert cao_uurloon(date(2004, 3, 1), "2", 2026, 3) == Decimal("15.42")
    assert cao_uurloon(date(2004, 3, 1), "2", 2027, 3) == Decimal("15.54")
    assert cao_uurloon(date(2004, 3, 1), "2", 2028, 3) == Decimal("15.66")
    assert cao_uurloon(date(2004, 3, 1), "2", 2030, 3) == Decimal("15.66")
    assert cao_uurloon(date(2004, 2, 29), "2", 2026, 1) == Decimal("15.30")
    assert cao_uurloon(date(2004, 2, 29), "2", 2026, 2) == Decimal("15.42")
    assert cao_uurloon(date(2008, 6, 1), "2", 2026, 6) is None

    oud = _periode(geldig_tot=date(2026, 9, 30), uurloon=Decimal("15"))
    nieuw = _periode(geldig_vanaf=date(2026, 10, 1), uurloon=None, naam="Later")
    schaal = deel_uit_uren(
        2026, 10, Decimal("10"), [], nieuw, [oud, nieuw],
        geboortedatum=date(2006, 4, 1), loonschaal="2",
    )
    assert schaal.uurloon == Decimal("12.24")
    assert schaal.uurloon_bron == "cao"
    geerfd = deel_uit_uren(2026, 10, Decimal("10"), [], nieuw, [oud, nieuw], loonschaal="")
    assert geerfd.uurloon == Decimal("15")
    assert geerfd.uurloon_bron == "vorige"
    ingevuld = _periode(geldig_vanaf=date(2026, 10, 1), uurloon=Decimal("11"))
    eigen = deel_uit_uren(
        2026, 10, Decimal("10"), [], ingevuld, [ingevuld],
        geboortedatum=date(2006, 4, 1), loonschaal="2",
    )
    assert eigen.uurloon == Decimal("11")
    assert eigen.uurloon_bron == "periode"


def test_overlap_wint_de_periode_die_het_laatst_ingaat():
    oud = _periode(naam="Oud", geldig_tot=date(2026, 10, 15))
    nieuw = _periode(naam="Nieuw", geldig_vanaf=date(2026, 10, 10))
    assert periode_op([oud, nieuw], date(2026, 10, 12)).naam == "Nieuw"
    assert periode_op([oud, nieuw], date(2026, 10, 9)).naam == "Oud"
