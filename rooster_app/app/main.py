"""Rooster: MyManus in de zijbalk van Home Assistant.

De pagina's praten met de lokale database. MyManus wordt aangeroepen vanuit
de achtergrondsync en vanaf de knop Vernieuwen, niet bij elke paginaweergave.
De iCloud-agenda alleen als je daar zelf op Instellingen om vraagt, en na
elke geslaagde sync als dat aan staat.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import secrets
import threading
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

import opslag
from agenda import maak_ics
from datums import maandnaam, parse_maand, WEEKDAGEN
from icloud import IcloudClient, IcloudFout, spiegel_naar_icloud, verwijder_voorbeeld, voorbeeld_oude_afspraken
from manus import ManusClient, ManusFout
from overzicht import bouw_maand
from salaris import standaard_periode_dicts
from synchronisatie import synchroniseer

VERSIE = "1.3.0"
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
log = logging.getLogger("rooster")

# Alleen de ingress-proxy van de Supervisor, niet het hele docker-netwerk
# 172.30.32.0/23. Een ander adres in dat netwerk is geen bewijs dat het
# verzoek uit de zijbalk komt. Tests en de smoke-test zetten INGRESS_NETWERK
# op hun eigen bron; in Home Assistant blijft deze standaard staan.
STANDAARD_INGRESS = "172.30.32.2"


def netwerken_uit(tekst: str) -> list:
    uit = []
    for stuk in tekst.split(","):
        stuk = stuk.strip()
        if not stuk:
            continue
        try:
            uit.append(ipaddress.ip_network(stuk))
        except ValueError:
            log.warning("INGRESS_NETWERK slaat '%s' over", stuk)
    return uit


INGRESS_NETWERKEN = netwerken_uit(os.environ.get("INGRESS_NETWERK", STANDAARD_INGRESS))
if not INGRESS_NETWERKEN:
    INGRESS_NETWERKEN = netwerken_uit(STANDAARD_INGRESS)


def afzender_mag(afzender: str, netwerken=None) -> bool:
    gekozen = INGRESS_NETWERKEN if netwerken is None else netwerken
    try:
        ip = ipaddress.ip_address(afzender)
    except ValueError:
        return False
    return any(ip in netwerk for netwerk in gekozen)

_SYNC = threading.Lock()


def _secret_key() -> str:
    vast = os.environ.get("SECRET_KEY")
    if vast:
        return vast
    pad = os.path.join(opslag.DATA_DIR, "secret_key")
    if os.path.exists(pad):
        with open(pad, encoding="utf-8") as bestand:
            sleutel = bestand.read().strip()
        if sleutel:
            return sleutel
    sleutel = secrets.token_hex(32)
    opslag.schrijf_bestand_0600(pad, sleutel)
    return sleutel


class IngressMiddleware:
    """Ingress zet de app onder een pad dat per installatie verschilt.

    Zonder SCRIPT_NAME wijzen de links naar de wortel van Home Assistant
    in plaats van naar deze add-on.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        pad = environ.get("HTTP_X_INGRESS_PATH")
        if pad:
            environ["SCRIPT_NAME"] = pad.rstrip("/")
        return self.wsgi_app(environ, start_response)


app = Flask(__name__)
app.secret_key = _secret_key()
app.wsgi_app = IngressMiddleware(app.wsgi_app)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["TEMPLATES_AUTO_RELOAD"] = os.environ.get("TEMPLATES_AUTO_RELOAD") == "1"

opslag.init_db()
opslag.zorg_voor_standen()


def nu() -> datetime:
    return datetime.now(AMSTERDAM)


def vandaag() -> date:
    return nu().date()


def csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def _euro(waarde) -> str:
    if waarde is None:
        return "—"
    bedrag = Decimal(waarde).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    negatief = bedrag < 0
    tekst = f"{abs(bedrag):.2f}"
    heel, centen = tekst.split(".")
    groepjes = []
    while heel:
        groepjes.append(heel[-3:])
        heel = heel[:-3]
    uit = ".".join(reversed(groepjes)) + "," + centen
    return ("−€ " if negatief else "€ ") + uit


def _uren(waarde, teken: bool = False) -> str:
    if waarde is None:
        return "—"
    bedrag = Decimal(waarde).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tekst = f"{abs(bedrag):.2f}".replace(".", ",")
    if not teken:
        return ("−" if bedrag < 0 else "") + tekst
    if bedrag > 0:
        return "+" + tekst
    if bedrag < 0:
        return "−" + tekst
    return tekst


def _nummer(waarde) -> str:
    """Decimalen weghalen, maar de nullen van het hele getal laten staan.

    50 mag niet 5 worden: rstrip op de hele tekst eet ook de nul van 50 op.
    """
    tekst = format(Decimal(waarde), "f")
    if "." in tekst:
        heel, fractie = tekst.split(".", 1)
        fractie = fractie.rstrip("0")
        tekst = heel if not fractie else f"{heel}.{fractie}"
    return tekst.replace(".", ",")


def _geleden(iso: str | None) -> str:
    if not iso:
        return "nog niet"
    try:
        toen = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if toen.tzinfo is None:
        toen = toen.replace(tzinfo=AMSTERDAM)
    minuten = int((nu() - toen).total_seconds() // 60)
    if minuten < 1:
        return "zojuist"
    if minuten < 60:
        return f"{minuten} min geleden" if minuten != 1 else "1 minuut geleden"
    uren = minuten // 60
    if uren < 48:
        return f"{uren} uur geleden" if uren != 1 else "1 uur geleden"
    dagen = uren // 24
    return f"{dagen} dagen geleden" if dagen != 1 else "1 dag geleden"


@app.context_processor
def sjabloon_basis():
    # Alleen tijdens een request. De agendafeed rendert geen pagina.
    try:
        ingress = via_ingress()
    except RuntimeError:
        ingress = False
    return {"via_ingress": ingress}


app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.globals["versie"] = VERSIE
app.jinja_env.globals["maandnaam"] = maandnaam
app.jinja_env.filters["euro"] = _euro
app.jinja_env.filters["uren"] = lambda waarde: _uren(waarde)
app.jinja_env.filters["uren_teken"] = lambda waarde: _uren(waarde, teken=True)
app.jinja_env.filters["nummer"] = _nummer
app.jinja_env.filters["kort"] = lambda dag: f"{WEEKDAGEN[dag.weekday()][:2]} {dag.day} {maandnaam(dag.year, dag.month).split()[0][:3]}"


def via_ingress() -> bool:
    if not request.environ.get("HTTP_X_INGRESS_PATH"):
        return False
    return afzender_mag(request.remote_addr or "")


def _csrf_ok() -> bool:
    verwacht = session.get("csrf_token") or ""
    gekregen = request.form.get("csrf_token") or ""
    if not verwacht or len(verwacht) != len(gekregen):
        return False
    return secrets.compare_digest(verwacht, gekregen)


def _terug(standaard: str) -> str:
    referer = request.referrer or ""
    if referer:
        stuk = urlsplit(referer)
        eigen = urlsplit(request.host_url)
        if stuk.netloc == eigen.netloc and stuk.path.startswith("/"):
            return stuk.path + (f"?{stuk.query}" if stuk.query else "")
    return standaard


@app.before_request
def poortwachter():
    # De agendafeed is het enige wat de iPhone rechtstreeks ophaalt. Die
    # zit achter een token in de URL. De rest hoort via de zijbalk, waar
    # Home Assistant al om een login heeft gevraagd.
    if request.endpoint == "agenda":
        return None
    if via_ingress():
        return None
    abort(403)


@app.before_request
def controleer_csrf():
    if request.method != "POST":
        return None
    if not _csrf_ok():
        abort(400, "Deze opdracht kwam niet van de app zelf.")
    return None


@app.errorhandler(403)
def geen_toegang(_fout):
    return render_template("geen_toegang.html"), 403


@app.route("/")
def index():
    gekozen = parse_maand(request.args.get("maand") or "")
    if gekozen is None:
        dag = vandaag()
        gekozen = (dag.year, dag.month)
    moment = nu()
    overzicht = bouw_maand(
        gekozen[0],
        gekozen[1],
        opslag.alle_diensten(),
        opslag.alle_verlof(),
        opslag.perioden_dicts(),
        opslag.alle_samenvattingen(),
        opslag.lees_verlofsaldo(),
        moment.date(),
        moment.hour * 60 + moment.minute,
        geboortedatum=_geboortedatum(),
        loonschaal=opslag.meta_get("loonschaal") or "",
    )
    _naam, _wachtwoord, bron = opslag.inloggegevens()
    return render_template(
        "index.html",
        o=overzicht,
        bron=bron,
        laatste_sync=_geleden(opslag.meta_get("laatste_gelukt")),
        laatste_fout=opslag.meta_get("laatste_fout") or "",
        winkel=opslag.meta_get("winkel") or "",
    )


@app.route("/instellingen", methods=["GET"])
def instellingen():
    return render_template("instellingen.html", **_instellingen_context())


def _instellingen_context():
    naam, _wachtwoord, bron = opslag.inloggegevens()
    token = opslag.agenda_token()
    extern = opslag.extern_adres()
    feed = f"{extern}/agenda/{token}.ics" if extern else ""
    rijen = opslag.perioden_dicts()
    from salaris import periode_uit_dict, uurloon_van

    perioden = []
    objecten = [periode_uit_dict(rij) for rij in rijen]
    for rij, periode in zip(rijen, objecten):
        geerfd = None
        if not (rij.get("uurloon") or "").strip():
            loon = uurloon_van(objecten, periode)
            if loon is not None:
                geerfd = loon
        perioden.append({**rij, "geerfd": geerfd})
    return {
        "bron": bron,
        "gebruikersnaam": naam if bron == "app" else "",
        "addon_naam": naam if bron == "addon" else "",
        "laatste_sync": _geleden(opslag.meta_get("laatste_gelukt")),
        "laatste_poging": _geleden(opslag.meta_get("laatste_poging")),
        "laatste_fout": opslag.meta_get("laatste_fout") or "",
        "winkel": opslag.meta_get("winkel") or "",
        "functie": opslag.meta_get("functie") or "",
        "token": token,
        "extern": extern,
        "feed": feed,
        "perioden": perioden,
        "sync_uren": opslag.sync_uren(),
        "alarm_uren": opslag.alarm_uren(),
        "geboortedatum": opslag.meta_get("geboortedatum") or "",
        "loonschaal": opslag.meta_get("loonschaal") or "",
        "loonschaal_voorstel": _loonschaal_voorstel(),
        "bronnen": _bronnen(),
        "icloud": _icloud_context(),
    }


def _icloud_context() -> dict:
    inst = opslag.lees_icloud()
    status = opslag.lees_icloud_status()
    voorbeeld = opslag.lees_icloud_voorbeeld()
    return {
        "email": inst["email"],
        "heeft_wachtwoord": bool(inst["wachtwoord"]),
        "aan": inst["aan"],
        "agenda_naam": inst["agenda_naam"],
        "agendas": opslag.lees_icloud_agendas(),
        "opruimen": inst["opruimen"],
        "marker": inst["marker"],
        "laatste": _geleden(status["laatste"] or None),
        "verslag": status["verslag"],
        "fout": status["fout"],
        "voorbeeld": voorbeeld,
    }


def _geboortedatum():
    tekst = opslag.meta_get("geboortedatum") or ""
    if not tekst:
        return None
    try:
        return date.fromisoformat(tekst)
    except ValueError:
        return None


def _loonschaal_voorstel():
    from salaris import cao_uurloon

    schaal = opslag.meta_get("loonschaal") or ""
    geboren = _geboortedatum()
    if schaal not in ("1", "2") or geboren is None:
        return None
    dag = vandaag()
    return cao_uurloon(geboren, schaal, dag.year, dag.month)


def _bronnen():
    from salaris import BRONNEN

    return [{"naam": naam, "url": url} for naam, url in BRONNEN]


@app.route("/instellingen/gegevens", methods=["POST"])
def gegevens_opslaan():
    _naam, _wachtwoord, bron = opslag.inloggegevens()
    if bron == "addon":
        flash("De inloggegevens staan in de add-onconfiguratie. Wijzig ze daar.", "fout")
        return redirect(url_for("instellingen"))
    gebruikersnaam = (request.form.get("gebruikersnaam") or "").strip()
    wachtwoord = request.form.get("wachtwoord")
    if not gebruikersnaam:
        flash("Vul een gebruikersnaam in.", "fout")
        return redirect(url_for("instellingen"))
    # Leeg veld: het bestaande wachtwoord laten staan. Anders kun je de
    # naam niet wijzigen zonder het wachtwoord opnieuw te typen.
    if wachtwoord == "":
        wachtwoord = None
        if not opslag.lees_geheim().get("wachtwoord"):
            flash("Vul ook het wachtwoord in. De app bewaart het lokaal, versleuteld is het niet.", "fout")
            return redirect(url_for("instellingen"))
    opslag.schrijf_geheim(gebruikersnaam, wachtwoord)
    # Een nieuw wachtwoord hoort niet verder te gaan met het oude token.
    opslag.meta_set("access_token", None)
    opslag.meta_set("token_geldig_tot", None)
    flash("Inloggegevens opgeslagen. Tik op Vernieuwen om ze te proberen.", "gelukt")
    return redirect(url_for("instellingen"))


@app.route("/instellingen/adres", methods=["POST"])
def adres_opslaan():
    adres = (request.form.get("extern_adres") or "").strip().rstrip("/")
    if adres and not (adres.startswith("https://") or adres.startswith("http://")):
        flash("Het adres moet met http:// of https:// beginnen.", "fout")
        return redirect(url_for("instellingen"))
    opslag.zet_extern_adres(adres)
    flash("Adres voor de agenda opgeslagen.", "gelukt")
    return redirect(url_for("instellingen"))


@app.route("/instellingen/alarm", methods=["POST"])
def alarm_opslaan():
    ruw = (request.form.get("alarm_uren") or "").strip()
    try:
        uren = int(ruw)
    except ValueError:
        flash("Vul een heel aantal uren in.", "fout")
        return redirect(url_for("instellingen"))
    if uren < 0 or uren > 48:
        flash("De herinnering kan van 0 tot 48 uur voor de dienst staan.", "fout")
        return redirect(url_for("instellingen"))
    opslag.zet_alarm_uren(uren)
    if uren == 0:
        flash("Herinnering uit. De feed en de gedeelde agenda krijgen geen alarm.", "gelukt")
    elif uren == 1:
        flash("Herinnering opgeslagen: 1 uur voor de dienst.", "gelukt")
    else:
        flash(f"Herinnering opgeslagen: {uren} uur voor de dienst.", "gelukt")
    return redirect(url_for("instellingen"))


@app.route("/instellingen/token", methods=["POST"])
def token_vernieuwen():
    opslag.nieuw_agenda_token()
    flash("Nieuwe agendalink. De oude link op je iPhone werkt niet meer.", "gelukt")
    return redirect(url_for("instellingen"))


@app.route("/instellingen/icloud", methods=["POST"])
def icloud_opslaan():
    if request.form.get("deel") == "opruimen":
        opruimen = request.form.get("opruimen") == "ja"
        marker = (request.form.get("marker") or "").strip()
        if opruimen and not marker:
            flash(
                "Vul de tekst in die in de oude Scriptable-afspraak staat, of zet opruimen uit.",
                "fout",
            )
            return redirect(url_for("instellingen"))
        opslag.schrijf_icloud({"opruimen": opruimen, "marker": marker})
        flash("Tekst voor het opruimen opgeslagen.", "gelukt")
        return redirect(url_for("instellingen"))

    email = (request.form.get("email") or "").strip()
    wachtwoord = request.form.get("wachtwoord")
    if not email:
        flash("Vul het e-mailadres van je Apple-id in.", "fout")
        return redirect(url_for("instellingen"))
    aan = request.form.get("aan") == "ja"
    if wachtwoord == "":
        wachtwoord = None
        if aan and not opslag.lees_icloud()["wachtwoord"]:
            flash("Vul het app-wachtwoord in. Het gewone wachtwoord van Apple werkt niet.", "fout")
            return redirect(url_for("instellingen"))
    opslag.schrijf_icloud({
        "email": email,
        "wachtwoord": wachtwoord,
        "aan": aan,
    })
    flash("iCloud-instellingen opgeslagen.", "gelukt")
    return redirect(url_for("instellingen"))


@app.route("/instellingen/icloud/agendas", methods=["POST"])
def icloud_agendas():
    inst = opslag.lees_icloud()
    if not inst["email"] or not inst["wachtwoord"]:
        flash("Sla eerst het e-mailadres en het app-wachtwoord op.", "fout")
        return redirect(url_for("instellingen"))
    try:
        agendas = IcloudClient(inst["email"], inst["wachtwoord"]).agenda_lijst()
    except IcloudFout as fout:
        log.info("iCloud-agenda's ophalen mislukt (%s)", fout.status or "netwerk")
        flash(str(fout), "fout")
        return redirect(url_for("instellingen"))
    if not agendas:
        flash("Apple gaf geen agenda's terug.", "fout")
        return redirect(url_for("instellingen"))
    opslag.zet_icloud_agendas(agendas)
    flash(f"{len(agendas)} agenda's gevonden. Kies er één.", "gelukt")
    return redirect(url_for("instellingen"))


@app.route("/instellingen/icloud/kiezen", methods=["POST"])
def icloud_kiezen():
    agendas = opslag.lees_icloud_agendas()
    try:
        index = int(request.form.get("agenda") or "-1")
    except ValueError:
        index = -1
    if index < 0 or index >= len(agendas):
        flash("Kies een agenda uit de lijst.", "fout")
        return redirect(url_for("instellingen"))
    gekozen = agendas[index]
    opslag.schrijf_icloud({"agenda_url": gekozen["url"], "agenda_naam": gekozen["naam"]})
    flash(f"Agenda gekozen: {gekozen['naam']}.", "gelukt")
    return redirect(url_for("instellingen"))


@app.route("/instellingen/icloud/voorbeeld", methods=["POST"])
def icloud_voorbeeld():
    try:
        verslag = voorbeeld_oude_afspraken(opslag, nu().date())
    except IcloudFout as fout:
        log.info("Voorbeeld oude afspraken mislukt (%s)", fout.status or "netwerk")
        flash(str(fout), "fout")
        return redirect(url_for("instellingen"))
    aantal = len(verslag["afspraken"])
    if aantal == 0:
        flash("Geen oude afspraken met die tekst in deze periode.", "gelukt")
    else:
        flash(f"{aantal} oude afspraken gevonden. Er is nog niets verwijderd.", "gelukt")
    return redirect(url_for("instellingen"))


@app.route("/instellingen/icloud/opruimen", methods=["POST"])
def icloud_opruimen():
    token = request.form.get("token") or ""
    try:
        verslag = verwijder_voorbeeld(opslag, token)
    except IcloudFout as fout:
        log.info("Opruimen mislukt (%s)", fout.status or "netwerk")
        flash(str(fout), "fout")
        return redirect(url_for("instellingen"))
    weg = verslag["verwijderd"]
    over = verslag["overgeslagen"]
    eerste = (
        f"{weg} oude afspraak verwijderd. "
        if weg == 1
        else f"{weg} oude afspraken verwijderd. "
    )
    if over == 0:
        tweede = "Niets overgeslagen."
    elif over == 1:
        tweede = "1 overgeslagen omdat die niet meer klopte."
    else:
        tweede = f"{over} overgeslagen omdat ze niet meer klopten."
    flash(eerste + tweede, "gelukt")
    return redirect(url_for("instellingen"))


@app.route("/instellingen/perioden", methods=["POST"])
def perioden_opslaan():
    actie = request.form.get("actie") or "opslaan"
    rijen = _rijen_uit_formulier(request.form)
    if actie.startswith("weg-"):
        try:
            index = int(actie.split("-", 1)[1])
        except ValueError:
            index = -1
        actie = "weg"
        rijen = [rij for nummer, rij in enumerate(rijen) if nummer != index]
    fouten = _controleer_perioden(rijen)
    if fouten and actie != "weg":
        for fout in fouten:
            flash(fout, "fout")
        return redirect(url_for("instellingen"))
    if actie == "weg" and fouten:
        # Na het schrappen kan de rest alsnog ongeldig zijn; dan bewaren we
        # niets en blijft de oude lijst staan.
        for fout in fouten:
            flash(fout, "fout")
        return redirect(url_for("instellingen"))
    if actie == "toevoegen":
        if fouten:
            for fout in fouten:
                flash(fout, "fout")
            return redirect(url_for("instellingen"))
        rijen.append(_nieuwe_periode(rijen))
    opslag.vervang_perioden(rijen)
    if actie == "toevoegen":
        flash("Periode toegevoegd. Vul aan wat er anders is en sla op.", "gelukt")
    elif actie == "weg":
        flash("Periode verwijderd.", "gelukt")
    else:
        flash("Contractperioden opgeslagen.", "gelukt")
    return redirect(url_for("instellingen"))


def _indices(form) -> list[int]:
    gevonden = set()
    for sleutel in form:
        staart = sleutel.rsplit("_", 1)[-1]
        if sleutel.endswith("_" + staart) and staart.isdigit():
            gevonden.add(int(staart))
    return sorted(gevonden)


def _rijen_uit_formulier(form) -> list[dict]:
    rijen = []
    for index in _indices(form):
        def veld(naam, idx=index):
            return form.get(f"{naam}_{idx}")

        rijen.append({
            "naam": (veld("naam") or "").strip(),
            "geldig_vanaf": (veld("geldig_vanaf") or "").strip(),
            "geldig_tot": (veld("geldig_tot") or "").strip(),
            "uren_per_week": (veld("uren_per_week") or "").strip().replace(",", "."),
            "uurloon": (veld("uurloon") or "").strip().replace(",", "."),
            "all_in": veld("all_in") == "ja",
            "flex_verlof_percentage": (veld("flex_verlof_percentage") or "").strip().replace(",", "."),
            "vakantiegeld_percentage": (veld("vakantiegeld_percentage") or "").strip().replace(",", "."),
            "vakantiegeld_maandelijks": veld("vakantiegeld_maandelijks") == "ja",
            "vast_maandloon": veld("vast_maandloon") == "ja",
            "pensioen_percentage": (veld("pensioen_percentage") or "").strip().replace(",", "."),
            "jaarfranchise": (veld("jaarfranchise") or "").strip().replace(",", "."),
            "fulltime_uren_per_week": (veld("fulltime_uren_per_week") or "").strip().replace(",", "."),
            "wga_percentage": (veld("wga_percentage") or "").strip().replace(",", "."),
            "avond_vanaf": (veld("avond_vanaf") or "").strip(),
            "avond_percentage": (veld("avond_percentage") or "").strip().replace(",", "."),
            "zondag_percentage": (veld("zondag_percentage") or "").strip().replace(",", "."),
            "zaterdag_percentage": (veld("zaterdag_percentage") or "").strip().replace(",", "."),
            "nacht_tot": (veld("nacht_tot") or "").strip(),
            "nacht_percentage": (veld("nacht_percentage") or "").strip().replace(",", "."),
            "zaterdag_vanaf": (veld("zaterdag_vanaf") or "").strip(),
            "feestdag_percentage": (veld("feestdag_percentage") or "").strip().replace(",", "."),
            "overwerk": veld("overwerk") == "ja",
            "overwerk_daguren": (veld("overwerk_daguren") or "").strip().replace(",", "."),
            "overwerk_weekuren": (veld("overwerk_weekuren") or "").strip().replace(",", "."),
            "overwerk_weken": (veld("overwerk_weken") or "").strip(),
            "overwerk_eerste_uren": (veld("overwerk_eerste_uren") or "").strip().replace(",", "."),
            "overwerk_eerste_percentage": (veld("overwerk_eerste_percentage") or "").strip().replace(",", "."),
            "overwerk_daarna_percentage": (veld("overwerk_daarna_percentage") or "").strip().replace(",", "."),
        })
    return rijen


def _getal(tekst: str, label: str, fouten: list[str], verplicht: bool = True) -> bool:
    if tekst == "":
        if verplicht:
            fouten.append(f"Vul {label} in.")
            return False
        return True
    try:
        if Decimal(tekst) < 0:
            raise ValueError
    except Exception:
        fouten.append(f"{label} moet een getal zijn van 0 of hoger.")
        return False
    return True


def _controleer_perioden(rijen: list[dict]) -> list[str]:
    from datums import klok_naar_minuten

    fouten = []
    if not rijen:
        return fouten
    for rij in rijen:
        naam = rij["naam"] or "een periode"
        if not rij["naam"]:
            fouten.append("Elke periode heeft een naam nodig.")
        try:
            vanaf = date.fromisoformat(rij["geldig_vanaf"])
        except ValueError:
            fouten.append(f"De begindatum van {naam} klopt niet.")
            vanaf = None
        if rij["geldig_tot"]:
            try:
                tot = date.fromisoformat(rij["geldig_tot"])
            except ValueError:
                fouten.append(f"De einddatum van {naam} klopt niet.")
                tot = None
            if vanaf and tot and tot < vanaf:
                fouten.append(f"Bij {naam} ligt de einddatum vóór de begindatum.")
        _getal(rij["uren_per_week"], f"de contracturen van {naam}", fouten)
        _getal(rij["uurloon"], f"het uurloon van {naam}", fouten, verplicht=False)
        for label, sleutel in (
            ("het flexverlof", "flex_verlof_percentage"),
            ("het vakantiegeld", "vakantiegeld_percentage"),
            ("de pensioenpremie", "pensioen_percentage"),
            ("de WGA-premie", "wga_percentage"),
            ("de avondtoeslag", "avond_percentage"),
            ("de zondagtoeslag", "zondag_percentage"),
            ("de zaterdagtoeslag", "zaterdag_percentage"),
            ("de nachttoeslag", "nacht_percentage"),
            ("de feestdagtoeslag", "feestdag_percentage"),
        ):
            if _getal(rij[sleutel], f"{label} van {naam}", fouten) and rij[sleutel]:
                if Decimal(rij[sleutel]) > 100:
                    fouten.append(f"{label.capitalize()} van {naam} kan niet boven de 100% liggen.")
        for label, sleutel in (
            ("de daggrens van het overwerk", "overwerk_daguren"),
            ("de weekgrens van het overwerk", "overwerk_weekuren"),
            ("de eerste overuren", "overwerk_eerste_uren"),
            ("het eerste overwerkpercentage", "overwerk_eerste_percentage"),
            ("het overwerkpercentage daarna", "overwerk_daarna_percentage"),
        ):
            _getal(rij[sleutel], f"{label} van {naam}", fouten)
        if rij["overwerk_weken"]:
            try:
                if int(rij["overwerk_weken"]) < 1:
                    raise ValueError
            except ValueError:
                fouten.append(f"Het aantal weken voor het overwerkgemiddelde van {naam} moet 1 of hoger zijn.")
        else:
            fouten.append(f"Vul het aantal weken voor het overwerk van {naam} in.")
        _getal(rij["jaarfranchise"], f"de jaarfranchise van {naam}", fouten)
        _getal(rij["fulltime_uren_per_week"], f"de fulltime-uren van {naam}", fouten)
        if klok_naar_minuten(rij["avond_vanaf"] or "") is None:
            fouten.append(f"Het avondtijdstip van {naam} moet eruitzien als 21:00.")
        if klok_naar_minuten(rij["nacht_tot"] or "") is None:
            fouten.append(f"Het nachttijdstip van {naam} moet eruitzien als 06:00.")
        if klok_naar_minuten(rij["zaterdag_vanaf"] or "") is None:
            fouten.append(f"Het zaterdagtijdstip van {naam} moet eruitzien als 18:00.")
    return fouten


def _nieuwe_periode(rijen: list[dict]) -> dict:
    if rijen:
        basis = dict(rijen[-1])
        basis["naam"] = "Nieuwe periode"
        basis["uurloon"] = ""
        if basis.get("geldig_tot"):
            # De dag ná de vorige einddatum, zodat twee perioden niet allebei
            # dezelfde dag claimen.
            try:
                vorige_tot = date.fromisoformat(rijen[-1]["geldig_tot"])
                basis["geldig_vanaf"] = (vorige_tot + timedelta(days=1)).isoformat()
            except ValueError:
                basis["geldig_vanaf"] = vandaag().isoformat()
        else:
            basis["geldig_vanaf"] = vandaag().isoformat()
        basis["geldig_tot"] = ""
        return basis
    voorbeeld = standaard_periode_dicts()[0]
    voorbeeld["naam"] = "Nieuwe periode"
    voorbeeld["geldig_vanaf"] = vandaag().isoformat()
    voorbeeld["geldig_tot"] = ""
    return voorbeeld


@app.route("/instellingen/loonschaal", methods=["POST"])
def loonschaal_opslaan():
    schaal = (request.form.get("loonschaal") or "").strip()
    if schaal not in ("", "1", "2"):
        flash("Kies geen schaal, schaal 1 of schaal 2.", "fout")
        return redirect(url_for("instellingen"))
    tekst = (request.form.get("geboortedatum") or "").strip()
    if tekst:
        try:
            date.fromisoformat(tekst)
        except ValueError:
            flash("De geboortedatum klopt niet.", "fout")
            return redirect(url_for("instellingen"))
    opslag.meta_set("loonschaal", schaal)
    opslag.meta_set("geboortedatum", tekst)
    flash("Loonschaal opgeslagen. Een uurloon dat je zelf invult blijft gelden.", "gelukt")
    return redirect(url_for("instellingen"))


@app.route("/vernieuwen", methods=["POST"])
def vernieuwen():
    uitkomst, bericht = voer_sync_uit()
    if uitkomst == "bezig":
        flash("Er loopt al een synchronisatie.", "fout")
    elif uitkomst == "fout":
        flash(bericht, "fout")
    else:
        flash(bericht, "gelukt")
    return redirect(_terug(url_for("index")))


def voer_sync_uit() -> tuple[str, str]:
    if not _SYNC.acquire(blocking=False):
        return "bezig", ""
    try:
        moment = nu()
        opslag.meta_set("laatste_poging", moment.replace(microsecond=0).isoformat())
        verslag = synchroniseer(ManusClient(), opslag, moment.date())
        if verslag["waarschuwingen"]:
            opslag.meta_set("laatste_fout", " ".join(verslag["waarschuwingen"]))
        else:
            opslag.meta_set("laatste_fout", "")
        opslag.meta_set("laatste_gelukt", moment.replace(microsecond=0).isoformat())
        tekst = (
            f"Rooster bijgewerkt: {verslag['weken']} weken opgehaald, "
            f"{verslag['periodes']} periodeoverzicht bewaard."
        )
        if verslag["waarschuwingen"]:
            tekst += " " + verslag["waarschuwingen"][0]
        tekst += _icloud_na_sync(moment.date())
        log.info("Sync klaar, %s weken", verslag["weken"])
        return "gelukt", tekst
    except ManusFout as fout:
        opslag.meta_set("laatste_fout", str(fout))
        log.info("Sync mislukt: %s", fout)
        return "fout", str(fout)
    except Exception:
        log.exception("Sync liep vast")
        opslag.meta_set("laatste_fout", "Synchroniseren is mislukt.")
        return "fout", "Synchroniseren is mislukt. Kijk in het add-onlog voor de technische melding."
    finally:
        _SYNC.release()


def _icloud_na_sync(vandaag: date) -> str:
    """Na een geslaagde MyManus-sync. Een fout hier laat het rooster staan."""
    try:
        verslag = spiegel_naar_icloud(opslag, vandaag)
    except Exception:
        log.exception("iCloud-agenda liep vast")
        opslag.zet_icloud_status(fout="De agenda bij Apple is niet bijgewerkt.")
        return " De agenda bij Apple is niet bijgewerkt."
    if not verslag.get("gedaan"):
        fout = verslag.get("fout") or ""
        return f" {fout}" if fout else ""
    if verslag["aangemaakt"] == verslag["bijgewerkt"] == verslag["verwijderd"] == 0 and not verslag.get("fout"):
        return " De gedeelde agenda was al gelijk."
    tekst = (
        f" Agenda: {verslag['aangemaakt']} nieuw, "
        f"{verslag['bijgewerkt']} bijgewerkt, {verslag['verwijderd']} verwijderd."
    )
    if verslag.get("fout"):
        tekst += " " + verslag["fout"]
    return tekst


def _sync_nodig() -> bool:
    _naam, _wachtwoord, bron = opslag.inloggegevens()
    if bron == "geen":
        return False
    laatste = opslag.meta_get("laatste_poging")
    if not laatste:
        return True
    try:
        toen = datetime.fromisoformat(laatste)
    except ValueError:
        return True
    if toen.tzinfo is None:
        toen = toen.replace(tzinfo=AMSTERDAM)
    return nu() - toen >= timedelta(hours=opslag.sync_uren())


def achtergrondlus() -> None:
    # Niet meteen bij het starten: Home Assistant is dan zelf nog bezig,
    # en een mislukte eerste poging hoort geen herstartstorm te worden.
    time.sleep(20)
    while True:
        try:
            if _sync_nodig():
                voer_sync_uit()
        except Exception:
            log.exception("Achtergrondsync sloeg over")
        time.sleep(60)


@app.route("/agenda/<token>.ics")
def agenda(token: str):
    verwacht = opslag.agenda_token()
    if len(token) != len(verwacht) or not secrets.compare_digest(token, verwacht):
        abort(404)
    diensten = opslag.alle_diensten()
    verloven = opslag.alle_verlof()
    inhoud = maak_ics(diensten, verloven, alarm_uren=opslag.alarm_uren())
    return (
        inhoud,
        200,
        {
            "Content-Type": "text/calendar; charset=utf-8",
            "Content-Disposition": "inline; filename=rooster.ics",
            "Cache-Control": "no-cache",
        },
    )


def _log_instellen() -> None:
    niveau = os.environ.get("LOG_LEVEL", "info").upper()
    if niveau == "NOTICE":
        niveau = "INFO"
    if niveau == "FATAL":
        niveau = "CRITICAL"
    if niveau == "TRACE":
        niveau = "DEBUG"
    logging.basicConfig(level=getattr(logging, niveau, logging.INFO), format="%(levelname)s %(message)s")


if __name__ == "__main__":
    _log_instellen()
    # 0.0.0.0 omdat de Supervisor de container via het docker-netwerk bereikt,
    # niet via localhost binnen de container.
    poort = int(os.environ.get("PORT", "8099"))
    if os.environ.get("ROOSTER_GEEN_ACHTERGROND") != "1":
        threading.Thread(target=achtergrondlus, name="sync", daemon=True).start()
    from waitress import serve

    log.info("Rooster luistert op poort %s", poort)
    serve(app, host="0.0.0.0", port=poort, threads=4)
