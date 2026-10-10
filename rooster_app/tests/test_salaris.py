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


def test_loonheffing_is_de_jaarberekening_gedeeld_door_twaalf():
    from salaris import algemene_heffingskorting, arbeidskorting, belasting_over_jaar

    sv = Decimal("2000")
    tabeljaar, tabel = tabellen_voor(2026)
    assert tabeljaar == 2026
    jaarlon = sv * 12
    verwacht = geld(
        (belasting_over_jaar(jaarlon, tabel) - algemene_heffingskorting(jaarlon, tabel) - arbeidskorting(jaarlon, tabel))
        / 12
    )
    assert loonheffing_maand(sv, 2026) == verwacht
    assert verwacht > 0
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


def test_toeslag_na_achttien_uur_en_op_zondag():
    periode = _periode()
    # Dinsdag 6 oktober 2026, 13:15–21:00, pauzes vóór 18:00.
    avond = toeslag_specificatie(
        date(2026, 10, 6), 13 * 60 + 15, 21 * 60,
        [(15 * 60, 15 * 60 + 15), (16 * 60 + 30, 17 * 60)],
        periode,
    )
    assert avond == [(Decimal("3.00"), Decimal("50"))]
    # Zondag 11 oktober, 09:00–18:00 met een uur pauze. Einde is precies 18:00,
    # dus alleen de zondagregel, niet ook nog de avond.
    zondag = toeslag_specificatie(
        date(2026, 10, 11), 9 * 60, 18 * 60, [(12 * 60, 13 * 60)], periode,
    )
    assert zondag == [(Decimal("8.00"), Decimal("50"))]


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


def test_zondagavond_stapelt_niet():
    periode = _periode(avond_percentage=Decimal("75"))
    uit = toeslag_specificatie(date(2026, 10, 11), 16 * 60, 22 * 60, [], periode)
    # Specificatie is (uren, percentage); de uren zijn de sleutel niet.
    per_percentage = {percentage: uren for uren, percentage in uit}
    assert per_percentage[Decimal("50")] == Decimal("2.00")
    assert per_percentage[Decimal("75")] == Decimal("4.00")


def test_zaterdag_telt_alleen_als_de_regel_aan_staat():
    periode = _periode()
    assert toeslag_specificatie(date(2026, 10, 10), 9 * 60, 17 * 60, [], periode) == []
    met_zaterdag = _periode(zaterdag_percentage=Decimal("25"))
    assert toeslag_specificatie(date(2026, 10, 10), 9 * 60, 17 * 60, [], met_zaterdag) == [
        (Decimal("8.00"), Decimal("25"))
    ]


def test_nachtdienst_krijgt_na_middernacht_de_volgende_dag():
    periode = _periode()
    # Vrijdag 22:00 tot zaterdag 02:00. Alleen het vrijdagstuk is avondtoeslag.
    uit = toeslag_specificatie(date(2026, 10, 9), 22 * 60, 2 * 60, [], periode)
    assert uit == [(Decimal("2.00"), Decimal("50"))]


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


def test_overlap_wint_de_periode_die_het_laatst_ingaat():
    oud = _periode(naam="Oud", geldig_tot=date(2026, 10, 15))
    nieuw = _periode(naam="Nieuw", geldig_vanaf=date(2026, 10, 10))
    assert periode_op([oud, nieuw], date(2026, 10, 12)).naam == "Nieuw"
    assert periode_op([oud, nieuw], date(2026, 10, 9)).naam == "Oud"
