"""Salarisregels, inclusief een all-in maandstrook als rekenvoorbeeld.

De bedragen zijn een synthetische strook met dezelfde opbouw als een
all-in hulpkrachtmaand: uurloon, toeslag à 50%, uitbetaald flexverlof en
8% vakantiegeld daarover. Het zijn geen opgeslagen persoonlijke tarieven;
het uurloon in de app blijft leeg tot je het zelf invult.
"""
from datetime import date
from decimal import Decimal

from salaris import (
    deel_uit_uren,
    loonheffing_maand,
    periode_op,
    standaard_periode_dicts,
    toeslag_specificatie,
    uitbetaling_van,
    uurloon_van,
)


def _periode(**wijzigingen):
    from salaris import Periode

    basis = dict(
        naam="Test",
        geldig_vanaf=date(2020, 1, 1),
        geldig_tot=None,
        uren_per_week=Decimal("38"),
        uurloon=Decimal("12.24"),
        all_in=True,
        flex_verlof_percentage=Decimal("9.23"),
        vakantiegeld_percentage=Decimal("8"),
        vakantiegeld_maandelijks=True,
        achteraf=True,
        pensioen_percentage=Decimal("6.1875"),
        jaarfranchise=Decimal("18680"),
        fulltime_uren_per_week=Decimal("38"),
        wga_percentage=Decimal("0.808"),
        avond_vanaf=18 * 60,
        avond_percentage=Decimal("50"),
        zondag_percentage=Decimal("50"),
        zaterdag_percentage=Decimal("0"),
    )
    basis.update(wijzigingen)
    return Periode(**basis)


def test_september_rekenvoorbeeld_komt_op_de_cent_uit():
    periode = _periode(geldig_tot=date(2026, 9, 30))
    deel = deel_uit_uren(
        2026, 9, Decimal("99.50"), [(Decimal("12.50"), Decimal("50"))],
        periode, [periode], dagen=30,
    )
    assert deel.salaris == Decimal("1217.88")
    assert deel.toeslag_bedrag == Decimal("76.50")
    assert deel.flex_uren == Decimal("9.18")
    assert deel.flex_bedrag == Decimal("112.36")
    assert deel.vakantiegeld == Decimal("106.42")
    assert deel.vakantiegeld_opbouw == Decimal("0")
    assert deel.bruto == Decimal("1513.16")
    assert deel.uit_maand == 10


def test_pensioen_wijkt_hooguit_een_cent_af_van_het_rekenvoorbeeld():
    periode = _periode()
    deel = deel_uit_uren(
        2026, 9, Decimal("99.50"), [(Decimal("12.50"), Decimal("50"))],
        periode, [periode], dagen=30,
    )
    # Officiële jaarfranchise 2026 naar rato van 99,50 uur op een fulltime
    # maand van 38 × 52 / 12. De voorbeeldstrook komt op 33,37 uit.
    assert abs(deel.pensioen - Decimal("33.37")) <= Decimal("0.02")
    assert abs(deel.sv_loon - Decimal("1479.79")) <= Decimal("0.05")
    assert abs(deel.grondslag - Decimal("539.27")) <= Decimal("0.20")


def test_loonheffing_blijft_binnen_een_euro_van_de_witte_tabel():
    heffing = loonheffing_maand(Decimal("1479.79"))
    assert abs(heffing - Decimal("36.50")) <= Decimal("1")
    periode = _periode()
    deel = deel_uit_uren(
        2026, 9, Decimal("99.50"), [(Decimal("12.50"), Decimal("50"))],
        periode, [periode], dagen=30,
    )
    uit = uitbetaling_van(2026, 10, [deel], [periode])
    assert abs(uit.loonheffing - Decimal("36.50")) <= Decimal("1")
    assert abs(uit.netto - Decimal("1431.33")) <= Decimal("1")


def test_oktober_betaalt_september_en_oktober_samen():
    oud = _periode(naam="Hulpkracht", geldig_tot=date(2026, 9, 30), achteraf=True, all_in=True)
    nieuw = _periode(
        naam="Parttime",
        geldig_vanaf=date(2026, 10, 1),
        geldig_tot=None,
        uurloon=None,
        all_in=False,
        vakantiegeld_maandelijks=False,
        achteraf=False,
        uren_per_week=Decimal("30"),
        wga_percentage=Decimal("0"),
    )
    perioden = [oud, nieuw]
    september = deel_uit_uren(
        2026, 9, Decimal("99.50"), [(Decimal("12.50"), Decimal("50"))],
        oud, perioden, dagen=30,
    )
    oktober = deel_uit_uren(
        2026, 10, Decimal("80"), [(Decimal("4"), Decimal("50"))],
        nieuw, perioden, dagen=31,
    )
    assert oktober.uurloon == Decimal("12.24")
    assert oktober.flex_bedrag == Decimal("0")
    assert oktober.vakantiegeld == Decimal("0")
    assert oktober.vakantiegeld_opbouw > 0
    assert (oktober.uit_jaar, oktober.uit_maand) == (2026, 10)
    assert (september.uit_jaar, september.uit_maand) == (2026, 10)

    samen = uitbetaling_van(2026, 10, [september, oktober], perioden)
    assert len(samen.delen) == 2
    assert samen.bruto == september.bruto + oktober.bruto
    apart = loonheffing_maand(september.sv_loon) + loonheffing_maand(oktober.sv_loon)
    assert samen.loonheffing > apart


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


def test_mei_betaalt_het_opgebouwde_vakantiegeld_en_heeft_hogere_heffing():
    periode = _periode(
        geldig_vanaf=date(2026, 10, 1),
        uurloon=Decimal("10"),
        all_in=False,
        vakantiegeld_maandelijks=False,
        achteraf=False,
        wga_percentage=Decimal("0"),
        uren_per_week=Decimal("30"),
    )
    delen = []
    for jaar, maand in (
        (2026, 10), (2026, 11), (2026, 12),
        (2027, 1), (2027, 2), (2027, 3), (2027, 4), (2027, 5),
    ):
        delen.append(deel_uit_uren(jaar, maand, Decimal("100"), [], periode, [periode], dagen=30))
    april = uitbetaling_van(2027, 4, delen, [periode])
    mei = uitbetaling_van(2027, 5, delen, [periode])
    assert april.vakantiegeld_extra == 0
    assert mei.vakantiegeld_extra == Decimal("640.00")
    assert mei.bruto == april.bruto + Decimal("640.00")
    assert mei.loonheffing > april.loonheffing


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
    assert september.all_in and september.achteraf and september.vakantiegeld_maandelijks
    assert oktober.naam == "Parttime verkoopmedewerker"
    assert not oktober.all_in and not oktober.achteraf and not oktober.vakantiegeld_maandelijks
    assert oktober.uren_per_week == Decimal("30")
    assert september.uurloon is None and oktober.uurloon is None


def test_overlap_wint_de_periode_die_het_laatst_ingaat():
    oud = _periode(naam="Oud", geldig_tot=date(2026, 10, 15))
    nieuw = _periode(naam="Nieuw", geldig_vanaf=date(2026, 10, 10))
    assert periode_op([oud, nieuw], date(2026, 10, 12)).naam == "Nieuw"
    assert periode_op([oud, nieuw], date(2026, 10, 9)).naam == "Oud"
