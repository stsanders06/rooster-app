"""Dagnummers en ISO-weken.

46303 is 10 oktober 2026. Het Excel-nulpunt van 30 december 1899 maakt
daar 8 oktober van; de app volgt het voorbeeld en de weekdagen uit het
rooster, niet die veelgehoorde uitleg.
"""
from datetime import date, timedelta

from datums import (
    bereik_rond,
    datum_naar_excel,
    excel_naar_datum,
    feestdagen,
    iso_week_dagen,
    maand_uit_periodenaam,
    pasen,
    weken_in_bereik,
)


def test_46303_is_10_oktober_2026():
    assert excel_naar_datum(46303) == date(2026, 10, 10)
    assert datum_naar_excel(date(2026, 10, 10)) == 46303


def test_heen_en_terug_voor_een_reeks_datums():
    dag = date(2020, 12, 28)
    while dag <= date(2027, 1, 10):
        assert excel_naar_datum(datum_naar_excel(dag)) == dag
        dag += timedelta(days=17)


def test_het_excel_nulpunt_van_30_december_1899_wijkt_twee_dagen_af():
    assert date(1899, 12, 30) + timedelta(days=46303) == date(2026, 10, 8)


def test_onbruikbaar_serienummer_wordt_geen_datum():
    assert excel_naar_datum(None) is None
    assert excel_naar_datum("geen-datum") is None
    assert excel_naar_datum(-1) is None


def test_week_53_van_2020_loopt_door_in_januari():
    maandag, zondag = iso_week_dagen(2020, 53)
    assert maandag == date(2020, 12, 28)
    assert zondag == date(2021, 1, 3)
    assert date(2021, 1, 1).isocalendar()[:2] == (2020, 53)


def test_week_53_van_2026_en_het_weekjaar_niet_het_kalenderjaar():
    maandag, zondag = iso_week_dagen(2026, 53)
    assert maandag == date(2026, 12, 28)
    assert zondag == date(2027, 1, 3)
    assert date(2026, 12, 31).isocalendar()[:2] == (2026, 53)
    assert date(2027, 1, 1).isocalendar()[:2] == (2026, 53)
    weken = weken_in_bereik(date(2026, 12, 28), date(2027, 1, 3))
    assert weken == [(2026, 53)]


def test_weken_in_bereik_zijn_uniek_en_oplopend():
    weken = weken_in_bereik(date(2026, 10, 1), date(2026, 10, 20))
    assert weken == sorted(set(weken))
    assert weken[0] == date(2026, 10, 1).isocalendar()[:2]
    assert weken[-1] == date(2026, 10, 20).isocalendar()[:2]


def test_bereik_dekt_twee_maanden_terug_en_vijf_weken_vooruit():
    van, tot = bereik_rond(date(2026, 10, 10))
    assert van == date(2026, 8, 1)
    assert tot == date(2026, 11, 14)


def test_10_oktober_2026_raakt_week_46_die_dan_nog_niet_vol_is():
    """Vijf weken vooruit eindigt op 14 november, midden in week 46.

    Die week is 9 tot en met 15 november. Het weeknummer klopt; MyManus
    heeft het rooster dan vaak nog niet. Dat is geen rekenfout.
    """
    _van, tot = bereik_rond(date(2026, 10, 10))
    weken = weken_in_bereik(date(2026, 8, 1), tot)
    assert weken[-1] == (2026, 46)
    maandag, zondag = iso_week_dagen(2026, 46)
    assert (maandag, zondag) == (date(2026, 11, 9), date(2026, 11, 15))
    assert maandag <= tot < zondag


def test_periodenaam_september_wint_van_de_datums():
    assert maand_uit_periodenaam("september 2026", date(2026, 8, 30), date(2026, 9, 28)) == (2026, 9)


def test_zonder_naam_valt_de_periode_in_de_maand_van_het_einde():
    assert maand_uit_periodenaam("", date(2026, 9, 1), date(2026, 9, 30)) == (2026, 9)


def test_feestdagen_volgen_pasen_koningsdag_en_het_lustrum():
    assert pasen(2026) == date(2026, 4, 5)
    assert pasen(2024) == date(2024, 3, 31)
    dagen_2026 = feestdagen(2026)
    assert date(2026, 4, 6) in dagen_2026
    assert date(2026, 5, 14) in dagen_2026
    assert date(2026, 5, 24) in dagen_2026
    assert date(2026, 5, 25) in dagen_2026
    assert date(2026, 4, 27) in dagen_2026
    assert date(2026, 4, 26) not in dagen_2026
    assert date(2026, 5, 5) not in dagen_2026
    # 27 april 2025 viel op een zondag, dus Koningsdag was de zaterdag ervoor.
    assert date(2025, 4, 26) in feestdagen(2025)
    assert date(2025, 4, 27) not in feestdagen(2025)
    assert date(2025, 5, 5) in feestdagen(2025)
    assert date(2030, 5, 5) in feestdagen(2030)
    assert date(2024, 5, 5) not in feestdagen(2024)
