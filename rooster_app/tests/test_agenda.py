"""De ICS-feed: titels, stabiele UID's en verlof als hele dag."""
from datetime import date, datetime, timezone

from agenda import (
    MARKERING,
    kern_van_ics,
    maak_ics,
    ontvouw_ics,
    scriptable_vorm,
    uid_dienst,
    zelfde_afspraak,
)

NU = datetime(2026, 10, 10, 8, 30, tzinfo=timezone.utc)


def _dienst(**wijzigingen):
    basis = dict(
        datum=date(2026, 10, 10),
        start_minuten=9 * 60,
        eind_minuten=18 * 60,
        pauze_minuten=45,
        totaal_minuten=495,
        winkel="Bouwmarkt Voorbeeld",
        winkel_code="BV01",
        afdeling="Verkoop",
        afdeling_code="7",
        afdeling_id=3,
        pauzes=[(12 * 60, 12 * 60 + 45)],
        uniek=uid_dienst(date(2026, 10, 10)),
    )
    basis.update(wijzigingen)
    return basis


def test_titel_is_eindtijd_en_notitie_volgt_het_scriptable_formaat():
    # 10:00–17:00 met 45 minuten pauze is 6 uur 15 werken. De titel noemt
    # alleen het einde, zoals de afspraken die er al stonden.
    dienst = _dienst(
        start_minuten=10 * 60,
        eind_minuten=17 * 60,
        pauze_minuten=45,
        totaal_minuten=6 * 60 + 15,
    )
    ics = maak_ics([dienst], [])
    kern = kern_van_ics(ics)
    assert kern["samenvatting"] == "17:00 - Bouwmarkt Voorbeeld"
    assert kern["omschrijving"] == "\n".join([
        "Locatie: Bouwmarkt Voorbeeld (BV01)",
        "Afdeling: 07 - Verkoop",
        "Werktijd: 6u15m",
        "Pauze: 0u45m",
        "",
        MARKERING,
    ])
    assert kern["alarm"] == "-PT2H"
    assert "DTSTART;TZID=Europe/Amsterdam:20261010T100000" in ics
    assert "DTEND;TZID=Europe/Amsterdam:20261010T170000" in ics
    assert "LOCATION" not in ics
    assert "\nURL:" not in ics
    assert "X-ROOSTER-APP" not in ics


def test_zonder_herinnering_geen_alarm():
    ics = maak_ics([_dienst()], [], alarm_uren=0)
    assert "VALARM" not in ics
    assert kern_van_ics(ics)["alarm"] == ""


def test_uid_blijft_gelijk_tussen_twee_keer_genereren():
    eerste = maak_ics([_dienst()], [], nu=NU)
    tweede = maak_ics([_dienst()], [], nu=NU)
    assert eerste == tweede
    assert "DTSTAMP:20261010T083000Z" in eerste
    assert f"UID:{uid_dienst(date(2026, 10, 10))}" in eerste


def test_uid_blijft_als_alleen_de_tijd_schuift():
    assert uid_dienst(date(2026, 10, 10), "42") == "dienst-2026-10-10-id-42@rooster-app"
    assert uid_dienst(date(2026, 10, 10), None, 1).endswith("nr-1@rooster-app")
    assert uid_dienst(date(2026, 10, 10), None, 1) != uid_dienst(date(2026, 10, 10), None, 2)


def test_kern_leest_de_afspraak_niet_de_tijdzone():
    ics = maak_ics([_dienst()], [], nu=NU)
    kern = kern_van_ics(ics)
    assert kern["start"] == "20261010T090000"
    assert kern["einde"] == "20261010T180000"
    assert kern["terugkerend"] is False
    assert kern["hele_dag"] is False
    assert "1970" not in kern["start"]
    assert scriptable_vorm(ics)


def test_zelfde_afspraak_negeert_de_tijdzone():
    ics = maak_ics([_dienst()], [], nu=NU)
    andere = ics.replace("TZOFFSETFROM:+0100", "TZOFFSETFROM:+0059", 1)
    assert ics != andere
    assert zelfde_afspraak(kern_van_ics(ics), kern_van_ics(andere))


def test_scriptable_vorm_is_het_vaste_patroon():
    ics = maak_ics([_dienst()], [], nu=NU)
    assert scriptable_vorm(ics)
    met_reeks = ics.replace("END:VEVENT", "RRULE:FREQ=WEEKLY\r\nEND:VEVENT", 1)
    assert scriptable_vorm(met_reeks) is False
    familie = "\r\n".join([
        "BEGIN:VCALENDAR",
        "BEGIN:VTIMEZONE",
        "DTSTART:19700329T020000",
        "RRULE:FREQ=YEARLY",
        "END:VTIMEZONE",
        "BEGIN:VEVENT",
        "SUMMARY:Verjaardag van oma",
        "DESCRIPTION:taart\\n\\n[AUTO-ADDED]",
        "DTSTART;TZID=Europe/Amsterdam:20261012T150000",
        "DTEND;TZID=Europe/Amsterdam:20261012T180000",
        "END:VEVENT",
        "END:VCALENDAR",
    ])
    assert scriptable_vorm(familie) is False
    assert kern_van_ics(familie)["start"] == "20261012T150000"
    hele_dag = maak_ics([], [{
        "van": date(2026, 11, 4),
        "tot": date(2026, 11, 5),
        "code": "V",
        "omschrijving": "Vakantie",
    }], nu=NU)
    assert scriptable_vorm(hele_dag) is False
    assert MARKERING not in hele_dag


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
    plat = "\n".join(ontvouw_ics(ics))
    assert "Verkoop\\, kassa\\; balie" in plat
    assert kern_van_ics(ics)["omschrijving"].split("\n")[1] == "Afdeling: 07 - Verkoop, kassa; balie"


def test_nachtdienst_eindigt_de_volgende_dag():
    ics = maak_ics([_dienst(start_minuten=22 * 60, eind_minuten=2 * 60)], [])
    assert "DTEND;TZID=Europe/Amsterdam:20261011T020000" in ics
    assert kern_van_ics(ics)["samenvatting"].startswith("02:00 - ")


def test_einde_op_2400_is_middernacht_de_volgende_dag():
    ics = maak_ics([_dienst(start_minuten=16 * 60, eind_minuten=24 * 60)], [], nu=NU)
    assert "DTSTART;TZID=Europe/Amsterdam:20261010T160000" in ics
    assert "DTEND;TZID=Europe/Amsterdam:20261011T000000" in ics
    assert "DTSTAMP:20261010T083000Z" in ics
