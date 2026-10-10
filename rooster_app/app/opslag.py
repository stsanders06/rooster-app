"""SQLite in /data, zodat een periode die MyManus niet meer teruggeeft blijft staan.

De API geeft vooral het actuele rooster en de laatst afgesloten periode. Wat
we eenmaal hebben opgehaald, gooien we niet weg als een latere sync het niet
meer meestuurt. Een opnieuw opgehaalde week vervangt wél die week: een
gewijzigde dienst hoort te verschuiven, geen tweede afspraak te worden.
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
                afdeling TEXT,
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
                achteraf INTEGER,
                pensioen_percentage TEXT,
                jaarfranchise TEXT,
                fulltime_uren_per_week TEXT,
                wga_percentage TEXT,
                avond_vanaf TEXT,
                avond_percentage TEXT,
                zondag_percentage TEXT,
                zaterdag_percentage TEXT
            );
            """
        )


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
                winkel, afdeling, afdeling_id, pauzes_json, uniek
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uniek) DO UPDATE SET
                datum = excluded.datum,
                start_minuten = excluded.start_minuten,
                eind_minuten = excluded.eind_minuten,
                pauze_minuten = excluded.pauze_minuten,
                totaal_minuten = excluded.totaal_minuten,
                winkel = excluded.winkel,
                afdeling = excluded.afdeling,
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
                dienst.get("afdeling") or "",
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
        "afdeling": rij["afdeling"] or "",
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
        "achteraf": bool(rij["achteraf"]),
        "pensioen_percentage": rij["pensioen_percentage"] or "",
        "jaarfranchise": rij["jaarfranchise"] or "",
        "fulltime_uren_per_week": rij["fulltime_uren_per_week"] or "",
        "wga_percentage": rij["wga_percentage"] or "",
        "avond_vanaf": rij["avond_vanaf"] or "18:00",
        "avond_percentage": rij["avond_percentage"] or "",
        "zondag_percentage": rij["zondag_percentage"] or "",
        "zaterdag_percentage": rij["zaterdag_percentage"] or "",
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
                    vakantiegeld_maandelijks, achteraf, pensioen_percentage,
                    jaarfranchise, fulltime_uren_per_week, wga_percentage,
                    avond_vanaf, avond_percentage, zondag_percentage, zaterdag_percentage
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    1 if periode.get("achteraf") else 0,
                    _tekst(periode.get("pensioen_percentage")),
                    _tekst(periode.get("jaarfranchise")),
                    _tekst(periode.get("fulltime_uren_per_week")),
                    _tekst(periode.get("wga_percentage")),
                    periode.get("avond_vanaf") or "18:00",
                    _tekst(periode.get("avond_percentage")),
                    _tekst(periode.get("zondag_percentage")),
                    _tekst(periode.get("zaterdag_percentage")),
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


def schrijf_geheim(gebruikersnaam: str, wachtwoord: str | None) -> None:
    """Wachtwoord None laat het bestaande staan. Een leeg wachtwoord wist het.

    Het bestand staat in /data en niet in de repository. De add-onopties
    winnen als die zijn ingevuld; dit is de route zonder herstart.
    """
    bestaand = lees_geheim()
    if wachtwoord is None:
        wachtwoord = bestaand.get("wachtwoord") or ""
    inhoud = {"gebruikersnaam": gebruikersnaam, "wachtwoord": wachtwoord}
    with open(GEHEIM_PATH, "w", encoding="utf-8") as bestand:
        json.dump(inhoud, bestand)
    os.chmod(GEHEIM_PATH, 0o600)


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


def agenda_token() -> str:
    import secrets

    token = meta_get("agenda_token")
    if token:
        return token
    token = secrets.token_urlsafe(24)
    meta_set("agenda_token", token)
    return token


def nieuw_agenda_token() -> str:
    import secrets

    token = secrets.token_urlsafe(24)
    meta_set("agenda_token", token)
    return token


def extern_adres() -> str:
    return (meta_get("extern_adres") or "").rstrip("/")


def zet_extern_adres(adres: str) -> None:
    meta_set("extern_adres", adres.strip().rstrip("/"))


def nu_iso(nu: datetime) -> str:
    return nu.replace(microsecond=0).isoformat()
