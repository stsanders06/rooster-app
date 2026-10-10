"""ICS-feed voor de iPhone en voor de agenda van Home Assistant.

De UID hangt alleen af van datum, tijden en afdeling. Een nieuwe sync mag
hetzelfde uur niet als een nieuwe afspraak laten verschijnen, anders vult
de agenda zich met dubbelen.
"""
from __future__ import annotations

from datetime import date, timedelta

from datums import minuten_naar_klok


def _escape(tekst: str) -> str:
    return (
        tekst.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _vouw(regel: str) -> str:
    """Regels langer dan 75 tekens vouwen, zoals RFC 5545 vraagt."""
    stukken = []
    while len(regel.encode("utf-8")) > 75:
        # Op tekens knippen is hier genoeg: de velden zijn kort en ASCII-zwaar.
        geknipt = regel[:70]
        stukken.append(geknipt)
        regel = " " + regel[70:]
    stukken.append(regel)
    return "\r\n".join(stukken)


def uid_dienst(datum: date, start: int, eind: int, afdeling_id: int | None) -> str:
    return f"dienst-{datum.isoformat()}-{int(start)}-{int(eind)}-{afdeling_id or 0}@rooster-app"


def uid_verlof(van: date, tot: date, code: str) -> str:
    return f"verlof-{van.isoformat()}-{tot.isoformat()}-{(code or 'v').lower()}@rooster-app"


def titel_dienst(start: int, eind: int, winkel: str) -> str:
    naam = winkel.strip() if winkel else "Dienst"
    return f"{minuten_naar_klok(start)}-{minuten_naar_klok(eind)} {naam}"


def omschrijving_dienst(afdeling: str, pauze_minuten: int, winkel: str) -> str:
    regels = []
    if afdeling:
        regels.append(f"Afdeling: {afdeling}")
    if pauze_minuten:
        regels.append(f"Pauze: {int(pauze_minuten)} minuten")
    if winkel:
        regels.append(winkel)
    return "\n".join(regels)


def _tijdzone() -> str:
    # Een vaste VTIMEZONE, zodat de iPhone de tijden als Amsterdam leest en
    # niet als zwevende kloktijden die bij een reis verschuiven.
    return "\r\n".join([
        "BEGIN:VTIMEZONE",
        "TZID:Europe/Amsterdam",
        "BEGIN:DAYLIGHT",
        "DTSTART:19700329T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
        "TZOFFSETFROM:+0100",
        "TZOFFSETTO:+0200",
        "TZNAME:CEST",
        "END:DAYLIGHT",
        "BEGIN:STANDARD",
        "DTSTART:19701025T030000",
        "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
        "TZOFFSETFROM:+0200",
        "TZOFFSETTO:+0100",
        "TZNAME:CET",
        "END:STANDARD",
        "END:VTIMEZONE",
    ])


def _stamp(dag: date, minuten: int) -> str:
    return f"{dag.strftime('%Y%m%d')}T{minuten_naar_klok(minuten).replace(':', '')}00"


def maak_ics(diensten: list[dict], verloven: list[dict]) -> str:
    regels = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Rooster App//NL",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Rooster",
        "X-WR-TIMEZONE:Europe/Amsterdam",
        _tijdzone(),
    ]
    for dienst in diensten:
        datum = dienst["datum"]
        start = int(dienst["start_minuten"])
        eind = int(dienst["eind_minuten"])
        eind_datum = datum
        if eind < start:
            eind_datum = datum + timedelta(days=1)
        titel = titel_dienst(start, eind, dienst.get("winkel") or "")
        tekst = omschrijving_dienst(
            dienst.get("afdeling") or "",
            int(dienst.get("pauze_minuten") or 0),
            dienst.get("winkel") or "",
        )
        uid = dienst.get("uniek") or uid_dienst(datum, start, eind, dienst.get("afdeling_id"))
        blok = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART;TZID=Europe/Amsterdam:{_stamp(datum, start)}",
            f"DTEND;TZID=Europe/Amsterdam:{_stamp(eind_datum, eind)}",
            f"SUMMARY:{_escape(titel)}",
        ]
        if tekst:
            blok.append(f"DESCRIPTION:{_escape(tekst)}")
        blok.append("END:VEVENT")
        regels.extend(_vouw(regel) for regel in blok)

    for verlof in verloven:
        van = verlof["van"]
        tot = verlof["tot"]
        # DTEND van een hele dag is de dag ná de laatste vrije dag.
        einde = tot + timedelta(days=1)
        titel = verlof.get("omschrijving") or "Verlof"
        uid = verlof.get("uniek") or uid_verlof(van, tot, verlof.get("code") or "")
        blok = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART;VALUE=DATE:{van.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{einde.strftime('%Y%m%d')}",
            f"SUMMARY:{_escape(titel)}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
        regels.extend(_vouw(regel) for regel in blok)

    regels.append("END:VCALENDAR")
    return "\r\n".join(regels) + "\r\n"
