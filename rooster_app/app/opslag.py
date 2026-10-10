"""SQLite in /data, zodat een periode die MyManus niet meer teruggeeft blijft staan.

Een afgesloten periode verandert niet meer, dus die halen we één keer op.
De nieuwste nog een keer: die kan net dicht zijn gegaan. Een opnieuw
opgehaalde week vervangt wél die week: een gewijzigde dienst hoort te
verschuiven, geen tweede afspraak te worden.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime

from decimal import Decimal

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
DB_PATH = os.path.join(DATA_DIR, "rooster.db")
GEHEIM_PATH = os.path.join(DATA_DIR, "geheim.json")
ICLOUD_PATH = os.path.join(DATA_DIR, "icloud.json")

os.makedirs(DATA_DIR, exist_ok=True)


def verbinding() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with verbinding() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                sleutel TEXT PRIMARY KEY,
                waarde TEXT
            );
            CREATE TABLE IF NOT EXISTS diensten (
                id INTEGER PRIMARY KEY,
                datum TEXT NOT NULL,
                start_minuten INTEGER NOT NULL,
                eind_minuten INTEGER NOT NULL,
                pauze_minuten INTEGER NOT NULL,
                totaal_minuten INTEGER NOT NULL,
                winkel TEXT,
                winkel_code TEXT,
                afdeling TEXT,
                afdeling_code TEXT,
                afdeling_id INTEGER,
                pauzes_json TEXT,
                uniek TEXT NOT NULL UNIQUE
            );
            CREATE INDEX IF NOT EXISTS diensten_datum ON diensten (datum);
            CREATE TABLE IF NOT EXISTS verlof (
                id INTEGER PRIMARY KEY,
                van TEXT NOT NULL,
                tot TEXT NOT NULL,
                code TEXT,
                omschrijving TEXT,
                uniek TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS periodesamenvatting (
                periode_id INTEGER PRIMARY KEY,
                naam TEXT,
                van TEXT,
                tot TEXT,
                jaar INTEGER,
                gerealiseerd_minuten REAL,
                compensatie_minuten REAL,
                plusmin_minuten REAL,
                verlof_minuten REAL,
                toeslagen REAL
            );
            CREATE TABLE IF NOT EXISTS verlofsaldo (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                nu_minuten REAL,
                einde_minuten REAL,
                opbouw_minuten REAL,
                opgenomen_minuten REAL
            );
            CREATE TABLE IF NOT EXISTS contractperioden (
                id INTEGER PRIMARY KEY,
                volgorde INTEGER NOT NULL,
                naam TEXT,
                geldig_vanaf TEXT,
                geldig_tot TEXT,
                uren_per_week TEXT,
                uurloon TEXT,
                all_in INTEGER,
                flex_verlof_percentage TEXT,
                vakantiegeld_percentage TEXT,
                vakantiegeld_maandelijks INTEGER,
                pensioen_percentage TEXT,
                jaarfranchise TEXT,
                fulltime_uren_per_week TEXT,
                wga_percentage TEXT,
                avond_vanaf TEXT,
                avond_percentage TEXT,
                zondag_percentage TEXT,
                zaterdag_percentage TEXT,
                vast_maandloon INTEGER NOT NULL DEFAULT 0,
                nacht_tot TEXT,
                nacht_percentage TEXT,
                zaterdag_vanaf TEXT,
                feestdag_percentage TEXT,
                overwerk INTEGER NOT NULL DEFAULT 1,
                overwerk_daguren TEXT,
                overwerk_weekuren TEXT,
                overwerk_weken INTEGER NOT NULL DEFAULT 4,
                overwerk_eerste_uren TEXT,
                overwerk_eerste_percentage TEXT,
                overwerk_daarna_percentage TEXT
            );
            """
        )
        kolommen = {rij[1] for rij in conn.execute("PRAGMA table_info(contractperioden)")}
        if "vast_maandloon" not in kolommen:
            conn.execute(
                "ALTER TABLE contractperioden ADD COLUMN vast_maandloon INTEGER NOT NULL DEFAULT 0"
            )
        # Versie 1.0 bewaarde of een periode een maand later uitbetaalde.
        # Het scherm rekent nu per gewerkte maand, dus die kolom heeft geen
        # betekenis meer.
        if "achteraf" in kolommen:
            conn.execute("ALTER TABLE contractperioden DROP COLUMN achteraf")
        # Een bestaande installatie heeft de cao-kolommen nog niet. De
        # standaard vult ze; de eenmalige update hieronder zet alleen de
        # oude meegeleverde 18:00/9,23 om, niet een zelf gekozen regel.
        extra = (
            ("nacht_tot", "TEXT"),
            ("nacht_percentage", "TEXT"),
            ("zaterdag_vanaf", "TEXT"),
            ("feestdag_percentage", "TEXT"),
            ("overwerk", "INTEGER NOT NULL DEFAULT 1"),
            ("overwerk_daguren", "TEXT"),
            ("overwerk_weekuren", "TEXT"),
            ("overwerk_weken", "INTEGER NOT NULL DEFAULT 4"),
            ("overwerk_eerste_uren", "TEXT"),
            ("overwerk_eerste_percentage", "TEXT"),
            ("overwerk_daarna_percentage", "TEXT"),
        )
        aanwezig = {rij[1] for rij in conn.execute("PRAGMA table_info(contractperioden)")}
        for naam, soort in extra:
            if naam not in aanwezig:
                conn.execute(f"ALTER TABLE contractperioden ADD COLUMN {naam} {soort}")
        vlag = conn.execute(
            "SELECT waarde FROM meta WHERE sleutel = ?", ("cao_2026_regels",)
        ).fetchone()
        if vlag is None:
            conn.execute(
                """
                UPDATE contractperioden
                SET flex_verlof_percentage = '9.2308'
                WHERE flex_verlof_percentage IN ('9.23', '9.230', '9.2300')
                """
            )
            conn.execute(
                """
                UPDATE contractperioden
                SET avond_vanaf = '21:00',
                    zaterdag_percentage = '50',
                    nacht_tot = COALESCE(nacht_tot, '06:00'),
                    nacht_percentage = COALESCE(nacht_percentage, '50'),
                    zaterdag_vanaf = COALESCE(zaterdag_vanaf, '18:00'),
                    feestdag_percentage = COALESCE(feestdag_percentage, '100')
                WHERE avond_vanaf IN ('18:00', '18:00:00')
                  AND COALESCE(zaterdag_percentage, '0') IN ('0', '0.0', '0.00', '')
                  AND zondag_percentage IN ('50', '50.0', '50.00')
                """
            )
            conn.execute(
                "INSERT INTO meta (sleutel, waarde) VALUES ('cao_2026_regels', 'ja')"
            )
        # Codes horen bij de notitie van de agenda. Een bestaande database
        # heeft de kolommen nog niet; de namen blijven bruikbaar zonder code.
        dienst_kolommen = {rij[1] for rij in conn.execute("PRAGMA table_info(diensten)")}
        if "winkel_code" not in dienst_kolommen:
            conn.execute("ALTER TABLE diensten ADD COLUMN winkel_code TEXT")
        if "afdeling_code" not in dienst_kolommen:
            conn.execute("ALTER TABLE diensten ADD COLUMN afdeling_code TEXT")


def meta_get(sleutel: str, standaard: str | None = None) -> str | None:
    with verbinding() as conn:
        rij = conn.execute("SELECT waarde FROM meta WHERE sleutel = ?", (sleutel,)).fetchone()
    if rij is None:
        return standaard
    return rij["waarde"]


def meta_set(sleutel: str, waarde: str | None) -> None:
    with verbinding() as conn:
        if waarde is None:
            conn.execute("DELETE FROM meta WHERE sleutel = ?", (sleutel,))
        else:
            conn.execute(
                "INSERT INTO meta (sleutel, waarde) VALUES (?, ?) "
                "ON CONFLICT(sleutel) DO UPDATE SET waarde = excluded.waarde",
                (sleutel, waarde),
            )


def _datum(tekst: str | None) -> date | None:
    if not tekst:
        return None
    return date.fromisoformat(tekst)


def _pauzes(tekst: str | None) -> list[tuple[int, int]]:
    if not tekst:
        return []
    ruw = json.loads(tekst)
    return [(int(van), int(tot)) for van, tot in ruw]


def vervang_week(van: date, tot: date, diensten: list[dict]) -> None:
    with verbinding() as conn:
        conn.execute("DELETE FROM diensten WHERE datum >= ? AND datum <= ?", (van.isoformat(), tot.isoformat()))
        _schrijf_diensten(conn, diensten)


def bewaar_diensten(diensten: list[dict]) -> None:
    """Zet diensten erbij of werk ze bij, zonder andere dagen te wissen.

    Bedoeld voor de upcoming-lijst, die maar een paar dagen dekt en de rest
    van de geschiedenis met rust moet laten.
    """
    with verbinding() as conn:
        _schrijf_diensten(conn, diensten)


def _schrijf_diensten(conn: sqlite3.Connection, diensten: list[dict]) -> None:
    for dienst in diensten:
        pauzes = dienst.get("pauzes") or []
        conn.execute(
            """
            INSERT INTO diensten (
                datum, start_minuten, eind_minuten, pauze_minuten, totaal_minuten,
                winkel, winkel_code, afdeling, afdeling_code, afdeling_id, pauzes_json, uniek
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uniek) DO UPDATE SET
                datum = excluded.datum,
                start_minuten = excluded.start_minuten,
                eind_minuten = excluded.eind_minuten,
                pauze_minuten = excluded.pauze_minuten,
                totaal_minuten = excluded.totaal_minuten,
                winkel = excluded.winkel,
                winkel_code = CASE
                    WHEN excluded.winkel_code != '' THEN excluded.winkel_code
                    ELSE diensten.winkel_code
                END,
                afdeling = excluded.afdeling,
                afdeling_code = CASE
                    WHEN excluded.afdeling_code != '' THEN excluded.afdeling_code
                    ELSE diensten.afdeling_code
                END,
                afdeling_id = excluded.afdeling_id,
                pauzes_json = excluded.pauzes_json
            """,
            (
                dienst["datum"].isoformat(),
                int(dienst["start_minuten"]),
                int(dienst["eind_minuten"]),
                int(dienst.get("pauze_minuten") or 0),
                int(dienst.get("totaal_minuten") or 0),
                dienst.get("winkel") or "",
                dienst.get("winkel_code") or "",
                dienst.get("afdeling") or "",
                dienst.get("afdeling_code") or "",
                dienst.get("afdeling_id"),
                json.dumps(pauzes),
                dienst["uniek"],
            ),
        )


def alle_diensten() -> list[dict]:
    with verbinding() as conn:
        rijen = conn.execute("SELECT * FROM diensten ORDER BY datum, start_minuten").fetchall()
    return [_dienst_dict(rij) for rij in rijen]


def diensten_tussen(van: date, tot: date) -> list[dict]:
    with verbinding() as conn:
        rijen = conn.execute(
            "SELECT * FROM diensten WHERE datum >= ? AND datum <= ? ORDER BY datum, start_minuten",
            (van.isoformat(), tot.isoformat()),
        ).fetchall()
    return [_dienst_dict(rij) for rij in rijen]


def _dienst_dict(rij: sqlite3.Row) -> dict:
    return {
        "datum": date.fromisoformat(rij["datum"]),
        "start_minuten": rij["start_minuten"],
        "eind_minuten": rij["eind_minuten"],
        "pauze_minuten": rij["pauze_minuten"],
        "totaal_minuten": rij["totaal_minuten"],
        "winkel": rij["winkel"] or "",
        "winkel_code": rij["winkel_code"] or "",
        "afdeling": rij["afdeling"] or "",
        "afdeling_code": rij["afdeling_code"] or "",
        "afdeling_id": rij["afdeling_id"],
        "pauzes": _pauzes(rij["pauzes_json"]),
        "uniek": rij["uniek"],
    }


def vervang_verlof_van_jaren(jaren: list[int], verloven: list[dict]) -> None:
    """Verlof van deze jaren vervangen, andere jaren laten staan.

    Een verlofjaren-antwoord is de volledige lijst van dat jaar. Wat er niet
    meer in staat, is ingetrokken en hoort ook uit de agenda.
    """
    with verbinding() as conn:
        for jaar in jaren:
            conn.execute(
                "DELETE FROM verlof WHERE van >= ? AND van <= ?",
                (f"{jaar:04d}-01-01", f"{jaar:04d}-12-31"),
            )
        for verlof in verloven:
            conn.execute(
                """
                INSERT INTO verlof (van, tot, code, omschrijving, uniek)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(uniek) DO UPDATE SET
                    van = excluded.van,
                    tot = excluded.tot,
                    code = excluded.code,
                    omschrijving = excluded.omschrijving
                """,
                (
                    verlof["van"].isoformat(),
                    verlof["tot"].isoformat(),
                    verlof.get("code") or "",
                    verlof.get("omschrijving") or "Verlof",
                    verlof["uniek"],
                ),
            )


def alle_verlof() -> list[dict]:
    with verbinding() as conn:
        rijen = conn.execute("SELECT * FROM verlof ORDER BY van").fetchall()
    return [
        {
            "van": date.fromisoformat(rij["van"]),
            "tot": date.fromisoformat(rij["tot"]),
            "code": rij["code"] or "",
            "omschrijving": rij["omschrijving"] or "Verlof",
            "uniek": rij["uniek"],
        }
        for rij in rijen
    ]


def bewaar_samenvatting(samenvatting: dict) -> None:
    plusmin = samenvatting.get("plusmin_minuten")
    with verbinding() as conn:
        conn.execute(
            """
            INSERT INTO periodesamenvatting (
                periode_id, naam, van, tot, jaar, gerealiseerd_minuten,
                compensatie_minuten, plusmin_minuten, verlof_minuten, toeslagen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(periode_id) DO UPDATE SET
                naam = excluded.naam,
                van = excluded.van,
                tot = excluded.tot,
                jaar = excluded.jaar,
                gerealiseerd_minuten = excluded.gerealiseerd_minuten,
                compensatie_minuten = excluded.compensatie_minuten,
                plusmin_minuten = excluded.plusmin_minuten,
                verlof_minuten = excluded.verlof_minuten,
                toeslagen = excluded.toeslagen
            """,
            (
                int(samenvatting["periode_id"]),
                samenvatting.get("naam") or "",
                samenvatting["van"].isoformat() if samenvatting.get("van") else None,
                samenvatting["tot"].isoformat() if samenvatting.get("tot") else None,
                samenvatting.get("jaar"),
                samenvatting.get("gerealiseerd_minuten") or 0,
                samenvatting.get("compensatie_minuten") or 0,
                plusmin,
                samenvatting.get("verlof_minuten") or 0,
                samenvatting.get("toeslagen"),
            ),
        )


def alle_samenvattingen() -> list[dict]:
    with verbinding() as conn:
        rijen = conn.execute("SELECT * FROM periodesamenvatting ORDER BY van").fetchall()
    uit = []
    for rij in rijen:
        uit.append({
            "periode_id": rij["periode_id"],
            "naam": rij["naam"] or "",
            "van": _datum(rij["van"]),
            "tot": _datum(rij["tot"]),
            "jaar": rij["jaar"],
            "gerealiseerd_minuten": rij["gerealiseerd_minuten"] or 0,
            "compensatie_minuten": rij["compensatie_minuten"] or 0,
            "plusmin_minuten": rij["plusmin_minuten"],
            "verlof_minuten": rij["verlof_minuten"] or 0,
            "toeslagen": rij["toeslagen"],
        })
    return uit


def bewaar_verlofsaldo(saldo: dict) -> None:
    with verbinding() as conn:
        conn.execute("DELETE FROM verlofsaldo")
        conn.execute(
            """
            INSERT INTO verlofsaldo (id, nu_minuten, einde_minuten, opbouw_minuten, opgenomen_minuten)
            VALUES (1, ?, ?, ?, ?)
            """,
            (
                saldo.get("nu_minuten"),
                saldo.get("einde_minuten"),
                saldo.get("opbouw_minuten"),
                saldo.get("opgenomen_minuten"),
            ),
        )


def lees_verlofsaldo() -> dict | None:
    with verbinding() as conn:
        rij = conn.execute("SELECT * FROM verlofsaldo WHERE id = 1").fetchone()
    if rij is None:
        return None
    return {
        "nu_minuten": rij["nu_minuten"],
        "einde_minuten": rij["einde_minuten"],
        "opbouw_minuten": rij["opbouw_minuten"],
        "opgenomen_minuten": rij["opgenomen_minuten"],
    }


def perioden_dicts() -> list[dict]:
    with verbinding() as conn:
        rijen = conn.execute("SELECT * FROM contractperioden ORDER BY volgorde, geldig_vanaf").fetchall()
    return [_periode_dict(rij) for rij in rijen]


def _periode_dict(rij: sqlite3.Row) -> dict:
    return {
        "id": rij["id"],
        "naam": rij["naam"] or "",
        "geldig_vanaf": rij["geldig_vanaf"] or "",
        "geldig_tot": rij["geldig_tot"] or "",
        "uren_per_week": rij["uren_per_week"] or "",
        "uurloon": rij["uurloon"] or "",
        "all_in": bool(rij["all_in"]),
        "flex_verlof_percentage": rij["flex_verlof_percentage"] or "",
        "vakantiegeld_percentage": rij["vakantiegeld_percentage"] or "",
        "vakantiegeld_maandelijks": bool(rij["vakantiegeld_maandelijks"]),
        "pensioen_percentage": rij["pensioen_percentage"] or "",
        "jaarfranchise": rij["jaarfranchise"] or "",
        "fulltime_uren_per_week": rij["fulltime_uren_per_week"] or "",
        "wga_percentage": rij["wga_percentage"] or "",
        "avond_vanaf": rij["avond_vanaf"] or "21:00",
        "avond_percentage": rij["avond_percentage"] or "",
        "zondag_percentage": rij["zondag_percentage"] or "",
        "zaterdag_percentage": rij["zaterdag_percentage"] or "",
        "vast_maandloon": bool(rij["vast_maandloon"]) if "vast_maandloon" in rij.keys() else False,
        "nacht_tot": (rij["nacht_tot"] if "nacht_tot" in rij.keys() else None) or "06:00",
        "nacht_percentage": (rij["nacht_percentage"] if "nacht_percentage" in rij.keys() else None) or "50",
        "zaterdag_vanaf": (rij["zaterdag_vanaf"] if "zaterdag_vanaf" in rij.keys() else None) or "18:00",
        "feestdag_percentage": (rij["feestdag_percentage"] if "feestdag_percentage" in rij.keys() else None) or "100",
        "overwerk": bool(rij["overwerk"]) if "overwerk" in rij.keys() and rij["overwerk"] is not None else True,
        "overwerk_daguren": (rij["overwerk_daguren"] if "overwerk_daguren" in rij.keys() else None) or "9",
        "overwerk_weekuren": (rij["overwerk_weekuren"] if "overwerk_weekuren" in rij.keys() else None) or "40",
        "overwerk_weken": str(rij["overwerk_weken"]) if "overwerk_weken" in rij.keys() and rij["overwerk_weken"] is not None else "4",
        "overwerk_eerste_uren": (rij["overwerk_eerste_uren"] if "overwerk_eerste_uren" in rij.keys() else None) or "2",
        "overwerk_eerste_percentage": (
            rij["overwerk_eerste_percentage"] if "overwerk_eerste_percentage" in rij.keys() else None
        ) or "125",
        "overwerk_daarna_percentage": (
            rij["overwerk_daarna_percentage"] if "overwerk_daarna_percentage" in rij.keys() else None
        ) or "150",
    }


def vervang_perioden(perioden: list[dict]) -> None:
    with verbinding() as conn:
        conn.execute("DELETE FROM contractperioden")
        for volgorde, periode in enumerate(perioden):
            conn.execute(
                """
                INSERT INTO contractperioden (
                    volgorde, naam, geldig_vanaf, geldig_tot, uren_per_week, uurloon,
                    all_in, flex_verlof_percentage, vakantiegeld_percentage,
                    vakantiegeld_maandelijks, pensioen_percentage,
                    jaarfranchise, fulltime_uren_per_week, wga_percentage,
                    avond_vanaf, avond_percentage, zondag_percentage, zaterdag_percentage,
                    vast_maandloon, nacht_tot, nacht_percentage, zaterdag_vanaf,
                    feestdag_percentage, overwerk, overwerk_daguren, overwerk_weekuren,
                    overwerk_weken, overwerk_eerste_uren, overwerk_eerste_percentage,
                    overwerk_daarna_percentage
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    volgorde,
                    periode.get("naam") or "",
                    periode.get("geldig_vanaf") or "",
                    periode.get("geldig_tot") or "",
                    _tekst(periode.get("uren_per_week")),
                    _tekst(periode.get("uurloon")),
                    1 if periode.get("all_in") else 0,
                    _tekst(periode.get("flex_verlof_percentage")),
                    _tekst(periode.get("vakantiegeld_percentage")),
                    1 if periode.get("vakantiegeld_maandelijks") else 0,
                    _tekst(periode.get("pensioen_percentage")),
                    _tekst(periode.get("jaarfranchise")),
                    _tekst(periode.get("fulltime_uren_per_week")),
                    _tekst(periode.get("wga_percentage")),
                    periode.get("avond_vanaf") or "21:00",
                    _tekst(periode.get("avond_percentage")),
                    _tekst(periode.get("zondag_percentage")),
                    _tekst(periode.get("zaterdag_percentage")),
                    1 if periode.get("vast_maandloon") else 0,
                    periode.get("nacht_tot") or "06:00",
                    _tekst(periode.get("nacht_percentage") if periode.get("nacht_percentage") not in (None, "") else "50"),
                    periode.get("zaterdag_vanaf") or "18:00",
                    _tekst(periode.get("feestdag_percentage") if periode.get("feestdag_percentage") not in (None, "") else "100"),
                    1 if periode.get("overwerk", True) else 0,
                    _tekst(periode.get("overwerk_daguren") or "9"),
                    _tekst(periode.get("overwerk_weekuren") or "40"),
                    int(periode.get("overwerk_weken") or 4),
                    _tekst(periode.get("overwerk_eerste_uren") or "2"),
                    _tekst(periode.get("overwerk_eerste_percentage") or "125"),
                    _tekst(periode.get("overwerk_daarna_percentage") or "150"),
                ),
            )


def zorg_voor_standen() -> None:
    """Alleen de allereerste keer. Een leegschoongemaakte lijst blijft leeg."""
    from salaris import standaard_periode_dicts

    if meta_get("perioden_gezaaid") == "ja":
        return
    if not perioden_dicts():
        vervang_perioden(standaard_periode_dicts())
    meta_set("perioden_gezaaid", "ja")


def _tekst(waarde) -> str:
    if waarde is None:
        return ""
    if isinstance(waarde, Decimal):
        return format(waarde, "f")
    return str(waarde)


def lees_opties() -> dict:
    pad = os.path.join(DATA_DIR, "options.json")
    if not os.path.exists(pad):
        return {}
    try:
        with open(pad, encoding="utf-8") as bestand:
            data = json.load(bestand)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def lees_geheim() -> dict:
    if not os.path.exists(GEHEIM_PATH):
        return {}
    try:
        with open(GEHEIM_PATH, encoding="utf-8") as bestand:
            data = json.load(bestand)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def schrijf_bestand_0600(pad: str, tekst: str) -> None:
    """Schrijf een geheim bestand dat vanaf het aanmaken modus 0600 heeft.

    open() gevolgd door chmod laat het bestand heel even leesbaar voor
    anderen. os.open zet de modus bij het aanmaken. Een bestand dat er al
    stond houdt anders zijn oude modus; fchmod corrigeert die vóór de inhoud.
    """
    fd = os.open(pad, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as bestand:
            bestand.write(tekst)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def schrijf_geheim(gebruikersnaam: str, wachtwoord: str | None) -> None:
    """Wachtwoord None laat het bestaande staan. Een leeg wachtwoord wist het.

    Het bestand staat in /data en niet in de repository. De add-onopties
    winnen als die zijn ingevuld; dit is de route zonder herstart. Een
    Home Assistant-backup neemt /data mee, dus ook dit bestand.
    """
    bestaand = lees_geheim()
    if wachtwoord is None:
        wachtwoord = bestaand.get("wachtwoord") or ""
    inhoud = {"gebruikersnaam": gebruikersnaam, "wachtwoord": wachtwoord}
    schrijf_bestand_0600(GEHEIM_PATH, json.dumps(inhoud))


def inloggegevens() -> tuple[str, str, str]:
    """(gebruikersnaam, wachtwoord, bron) waarbij bron addon, app of geen is.

    Zijn de add-onopties ingevuld, dan gelden die. Anders wat op de
    instellingenpagina is opgeslagen. Een half ingevuld paar telt niet:
    inloggen met alleen een gebruikersnaam heeft geen zin.
    """
    opties = lees_opties()
    naam = str(opties.get("gebruikersnaam") or "").strip()
    wachtwoord = str(opties.get("wachtwoord") or "")
    if naam and wachtwoord:
        return naam, wachtwoord, "addon"
    geheim = lees_geheim()
    naam = str(geheim.get("gebruikersnaam") or "").strip()
    wachtwoord = str(geheim.get("wachtwoord") or "")
    if naam and wachtwoord:
        return naam, wachtwoord, "app"
    return "", "", "geen"


def sync_uren() -> int:
    ruw = lees_opties().get("sync_uren", 4)
    try:
        uren = int(ruw)
    except (TypeError, ValueError):
        uren = 4
    return min(168, max(1, uren))


def alarm_uren() -> int:
    """Uren voor de dienst dat de herinnering afgaat. Standaard twee."""
    ruw = meta_get("alarm_uren")
    if ruw is None or ruw == "":
        return 2
    try:
        uren = int(ruw)
    except ValueError:
        return 2
    return min(48, max(0, uren))


def zet_alarm_uren(uren: int) -> None:
    meta_set("alarm_uren", str(int(uren)))


def lees_icloud() -> dict:
    """iCloud-instellingen uit /data. Zonder bestand is alles uit."""
    ruw = _lees_json(ICLOUD_PATH)
    return {
        "email": str(ruw.get("email") or "").strip(),
        "wachtwoord": str(ruw.get("wachtwoord") or ""),
        "aan": bool(ruw.get("aan")),
        "agenda_url": str(ruw.get("agenda_url") or ""),
        "agenda_naam": str(ruw.get("agenda_naam") or ""),
        "kenmerk": str(ruw.get("kenmerk") or ""),
    }


def schrijf_icloud(wijziging: dict) -> None:
    """Bewaar de iCloud-instellingen, modus 0600, nooit in de repository.

    wachtwoord None laat het bestaande staan. Het kenmerk wordt één keer
    gekozen: de UID's in de gedeelde agenda hangen daarvan af. Een ander
    e-mailadres hoort bij een ander account, dus de gekozen agenda vervalt.
    """
    import secrets

    bestaand = lees_icloud()
    wachtwoord = wijziging.get("wachtwoord", None)
    if wachtwoord is None:
        wachtwoord = bestaand["wachtwoord"]
    email = str(wijziging.get("email", bestaand["email"]) or "").strip()
    kenmerk = bestaand["kenmerk"] or secrets.token_hex(8)
    if "kenmerk" in wijziging and str(wijziging.get("kenmerk") or "").strip():
        # Een leeg bestand mag het kenmerk uit de agenda overnemen. Anders
        # zet de volgende sync een tweede reeks naast de bestaande diensten.
        kenmerk = str(wijziging["kenmerk"]).strip()
    # Een ander Apple-id hoort bij een ander account. Alleen als deze
    # aanroep zelf geen agenda meegeeft, vervalt de vorige keuze. Anders
    # raakt de eerste keer opslaan — e-mail en agenda samen — de agenda kwijt.
    if email != bestaand["email"] and "agenda_url" not in wijziging:
        agenda_url = ""
        agenda_naam = ""
    else:
        agenda_url = str(wijziging.get("agenda_url", bestaand["agenda_url"]) or "")
        agenda_naam = str(wijziging.get("agenda_naam", bestaand["agenda_naam"]) or "")
    inhoud = {
        "email": email,
        "wachtwoord": wachtwoord or "",
        "aan": bool(wijziging.get("aan", bestaand["aan"])),
        "agenda_url": agenda_url,
        "agenda_naam": agenda_naam,
        "kenmerk": kenmerk,
    }
    if inhoud["email"] != bestaand["email"]:
        meta_set("icloud_vorige", None)
        meta_set("icloud_vorige_voorbeeld", None)
    schrijf_bestand_0600(ICLOUD_PATH, json.dumps(inhoud))


def _lees_json(pad: str) -> dict:
    if not os.path.exists(pad):
        return {}
    try:
        with open(pad, encoding="utf-8") as bestand:
            data = json.load(bestand)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def zet_icloud_agendas(agendas: list[dict]) -> None:
    meta_set("icloud_agendas", json.dumps(agendas))


def lees_icloud_agendas() -> list[dict]:
    ruw = meta_get("icloud_agendas")
    if not ruw:
        return []
    try:
        data = json.loads(ruw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    uit = []
    for item in data:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        naam = str(item.get("naam") or "")
        if url and naam:
            uit.append({"url": url, "naam": naam, "label": str(item.get("label") or naam)})
    return uit


def zet_icloud_status(verslag: str | None = None, fout: str | None = None, laatste: str | None = None) -> None:
    if laatste is not None:
        meta_set("icloud_laatste", laatste)
    if verslag is not None:
        meta_set("icloud_verslag", verslag)
    if fout is not None:
        meta_set("icloud_fout", fout)


def lees_icloud_status() -> dict:
    return {
        "laatste": meta_get("icloud_laatste") or "",
        "verslag": meta_get("icloud_verslag") or "",
        "fout": meta_get("icloud_fout") or "",
    }


def ontkoppel_icloud() -> None:
    """Apple-id en app-wachtwoord weg. Het kenmerk blijft, anders ontstaan dubbelen."""
    bestaand = lees_icloud()
    inhoud = {
        "email": "",
        "wachtwoord": "",
        "aan": False,
        "agenda_url": "",
        "agenda_naam": "",
        "kenmerk": bestaand["kenmerk"],
    }
    meta_set("icloud_vorige_voorbeeld", None)
    meta_set("icloud_agendas", None)
    meta_set("icloud_vorige", None)
    schrijf_bestand_0600(ICLOUD_PATH, json.dumps(inhoud))


def zet_vorige_agenda(url: str, naam: str) -> None:
    if not url:
        meta_set("icloud_vorige", None)
        meta_set("icloud_vorige_voorbeeld", None)
        return
    meta_set("icloud_vorige", json.dumps({"url": url, "naam": naam}))
    meta_set("icloud_vorige_voorbeeld", None)


def lees_vorige_agenda() -> dict | None:
    ruw = meta_get("icloud_vorige")
    if not ruw:
        return None
    try:
        data = json.loads(ruw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.get("url"):
        return None
    return {"url": str(data["url"]), "naam": str(data.get("naam") or "")}


def zet_vorige_voorbeeld(voorbeeld: dict | None) -> None:
    if voorbeeld is None:
        meta_set("icloud_vorige_voorbeeld", None)
        return
    meta_set("icloud_vorige_voorbeeld", json.dumps(voorbeeld))


def lees_vorige_voorbeeld() -> dict | None:
    ruw = meta_get("icloud_vorige_voorbeeld")
    if not ruw:
        return None
    try:
        data = json.loads(ruw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def nu_iso(nu: datetime) -> str:
    return nu.replace(microsecond=0).isoformat()
