"""De ICS-feed: titels, stabiele UID's en verlof als hele dag."""
from datetime import date

from agenda import maak_ics, uid_dienst


def _dienst(**wijzigingen):
    basis = dict(
        datum=date(2026, 10, 10),
        start_minuten=9 * 60,
        eind_minuten=18 * 60,
        pauze_minuten=45,
        totaal_minuten=495,
        winkel="Bouwmarkt Voorbeeld",
        afdeling="Verkoop",
        afdeling_id=3,
        pauzes=[(12 * 60, 12 * 60 + 45)],
        uniek=uid_dienst(date(2026, 10, 10), 9 * 60, 18 * 60, 3),
    )
    basis.update(wijzigingen)
    return basis


def test_titel_tijd_en_winkel_omschrijving_heeft_afdeling_en_pauze():
    ics = maak_ics([_dienst()], [])
    assert "SUMMARY:09:00-18:00 Bouwmarkt Voorbeeld" in ics
    assert "Afdeling: Verkoop" in ics
    assert "Pauze: 45 minuten" in ics
    assert "DTSTART;TZID=Europe/Amsterdam:20261010T090000" in ics
    assert "DTEND;TZID=Europe/Amsterdam:20261010T180000" in ics


def test_uid_blijft_gelijk_tussen_twee_keer_genereren():
    eerste = maak_ics([_dienst()], [])
    tweede = maak_ics([_dienst()], [])
    assert eerste == tweede
    assert f"UID:{uid_dienst(date(2026, 10, 10), 9 * 60, 18 * 60, 3)}" in eerste


def test_verlof_is_een_hele_dag_tot_en_met_de_laatste_dag():
    ics = maak_ics([], [{
        "van": date(2026, 11, 4),
        "tot": date(2026, 11, 5),
        "code": "V",
        "omschrijving": "Vakantie",
        "uniek": "verlof-2026-11-04-2026-11-05-v@rooster-app",
    }])
    assert "DTSTART;VALUE=DATE:20261104" in ics
    assert "DTEND;VALUE=DATE:20261106" in ics
    assert "SUMMARY:Vakantie" in ics
    assert "TRANSP:TRANSPARENT" in ics


def test_komma_en_puntkomma_worden_geescaped():
    ics = maak_ics([_dienst(afdeling="Verkoop, kassa; balie")], [])
    assert "Verkoop\\, kassa\\; balie" in ics


def test_nachtdienst_eindigt_de_volgende_dag():
    ics = maak_ics([_dienst(start_minuten=22 * 60, eind_minuten=2 * 60)], [])
    assert "DTEND;TZID=Europe/Amsterdam:20261011T020000" in ics
