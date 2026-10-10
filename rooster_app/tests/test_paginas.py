"""Pagina's en ingress. Een maand toont alleen de uren van die maand."""
import pathlib
from datetime import date
from decimal import Decimal

import opslag
from conftest import INGRESS, csrf_uit
from main import _euro
from overzicht import bouw_maand
from salaris import periode_uit_dict, standaard_periode_dicts


ROOT = pathlib.Path(__file__).resolve().parents[2]


def _perioden_met_loon(loon="15"):
    rijen = standaard_periode_dicts()
    rijen[0]["uurloon"] = loon
    opslag.vervang_perioden(rijen)


def _september_dicht():
    opslag.bewaar_samenvatting({
        "periode_id": 4242,
        "naam": "september 2026",
        "van": date(2026, 9, 1),
        "tot": date(2026, 9, 30),
        "jaar": 2026,
        "gerealiseerd_minuten": 80 * 60,
        "compensatie_minuten": 5 * 60,
        "plusmin_minuten": 10 * 60,
        "verlof_minuten": 0,
        "toeslagen": 0,
    })


def _oktober_dienst():
    opslag.bewaar_diensten([{
        "datum": date(2026, 10, 11),
        "start_minuten": 10 * 60,
        "eind_minuten": 16 * 60,
        "pauze_minuten": 30,
        "totaal_minuten": 330,
        "winkel": "Bouwmarkt Voorbeeld",
        "afdeling": "Verkoop",
        "afdeling_id": 3,
        "pauzes": [(12 * 60, 12 * 60 + 30)],
        "uniek": "dienst-2026-10-11-600-960-3@rooster-app",
    }])


def test_zonder_ingress_geen_dashboard(client):
    antwoord = client.get("/")
    assert antwoord.status_code == 403
    assert "zijbalk" in antwoord.get_data(as_text=True)


def test_vervalste_header_van_buiten_het_netwerk_komt_er_niet_in(client):
    antwoord = client.get(
        "/",
        headers={"X-Ingress-Path": "/api/hassio_ingress/abc"},
        environ_base={"REMOTE_ADDR": "8.8.8.8"},
    )
    assert antwoord.status_code == 403


def test_ingress_prefix_komt_in_de_links(client):
    antwoord = client.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
    html = antwoord.get_data(as_text=True)
    assert antwoord.status_code == 200
    assert 'href="/api/hassio_ingress/abc/instellingen"' in html


def _scherm(jaar, maand):
    return bouw_maand(
        jaar,
        maand,
        opslag.alle_diensten(),
        opslag.alle_verlof(),
        opslag.perioden_dicts(),
        opslag.alle_samenvattingen(),
        opslag.lees_verlofsaldo(),
        date(2026, 10, 10),
        12 * 60,
    )


def test_oktober_toont_alleen_de_oktoberuren(client):
    _perioden_met_loon()
    _september_dicht()
    _oktober_dienst()
    oktober = _scherm(2026, 10)
    september = _scherm(2026, 9)
    assert len(oktober["werk"]) == 1
    assert len(september["werk"]) == 1
    assert oktober["werk"][0].uren == Decimal("5.50")
    assert september["werk"][0].uren == Decimal("80.00")
    assert oktober["werk"][0].bruto != september["werk"][0].bruto
    assert oktober["werk"][0].vakantiegeld_opbouw > 0
    assert oktober["vakantiegeld_open"] == oktober["werk"][0].vakantiegeld_opbouw
    assert oktober["werk"][0].netto == (
        oktober["werk"][0].sv_loon - oktober["werk"][0].wga - oktober["werk"][0].loonheffing
    )

    antwoord = client.get("/?maand=2026-10", headers=INGRESS)
    html = antwoord.get_data(as_text=True)
    assert antwoord.status_code == 200
    assert "oktober 2026" in html
    loonheffing = html.index("Loonheffing")
    wga = html.index("WGA-premie")
    netto = html.index('class="netto"')
    assert loonheffing < wga < netto
    assert "over het sv-loon" in html
    assert "gepland/geschat" in html
    assert "Twee maanden in één uitbetaling" not in html
    assert "Uitbetaald in" not in html
    assert "80,00" not in html
    assert "Hulpkracht" not in html
    assert "Parttime verkoopmedewerker" in html
    # Zondag 10:00–16:00 is 50% toeslag. 50 mag niet als 5% op het scherm.
    assert "uur à 50%" in html
    assert "uur à 5%" not in html
    assert "Bouwmarkt Voorbeeld" in html
    assert _euro(oktober["werk"][0].netto) in html
    assert _euro(september["werk"][0].bruto) not in html
    assert _euro(september["werk"][0].netto) not in html
    assert "Vakantiegeld opgebouwd" in html
    assert "Netto, schatting, over de uren van deze maand." in html

    sep_html = client.get("/?maand=2026-09", headers=INGRESS).get_data(as_text=True)
    assert "september 2026" in sep_html
    assert "definitief" in sep_html
    assert "80,00" in sep_html
    assert "Twee maanden in één uitbetaling" not in sep_html
    assert "Uitbetaald in" not in sep_html
    assert "Parttime" not in sep_html
    assert _euro(september["werk"][0].netto) in sep_html
    assert _euro(oktober["werk"][0].netto) not in sep_html
    assert _euro(oktober["werk"][0].bruto) not in sep_html


def test_oude_wga_nul_wordt_eenmalig_de_standaard():
    rijen = opslag.perioden_dicts()
    rijen[0]["wga_percentage"] = "0"
    rijen[1]["wga_percentage"] = "1.25"
    opslag.vervang_perioden(rijen)
    opslag.meta_set("wga_standaard_gezet", None)
    opslag.vul_wga_standaard()
    bijgewerkt = opslag.perioden_dicts()
    assert bijgewerkt[0]["wga_percentage"] == "0.808"
    assert bijgewerkt[1]["wga_percentage"] == "1.25"
    # Een bewuste 0 daarna blijft 0.
    bijgewerkt[0]["wga_percentage"] = "0"
    opslag.vervang_perioden(bijgewerkt)
    opslag.vul_wga_standaard()
    assert opslag.perioden_dicts()[0]["wga_percentage"] == "0"


def test_agendafeed_bestaat_niet(client):
    # Zonder zijbalk blijft de poortwachter dicht. Mét zijbalk is er geen route.
    assert client.get("/agenda/geheim.ics").status_code == 403
    antwoord = client.get("/agenda/geheim.ics", headers=INGRESS)
    assert antwoord.status_code == 404
    assert b"BEGIN:VCALENDAR" not in antwoord.data


def test_vernieuwen_zonder_gegevens_gaat_niet_naar_buiten(client):
    pagina = client.get("/instellingen", headers=INGRESS)
    token = csrf_uit(pagina.get_data(as_text=True))
    antwoord = client.post(
        "/vernieuwen",
        data={"csrf_token": token},
        headers=INGRESS,
        follow_redirects=True,
    )
    assert "gebruikersnaam" in antwoord.get_data(as_text=True)


def test_post_zonder_csrf_wordt_geweigerd(client):
    antwoord = client.post("/vernieuwen", data={}, headers=INGRESS)
    assert antwoord.status_code == 400


def test_instellingen_bewaart_een_uurloon(client):
    pagina = client.get("/instellingen", headers=INGRESS)
    html = pagina.get_data(as_text=True)
    assert "Hulpkracht" in html
    assert "Parttime verkoopmedewerker" in html
    assert "Een maand later" not in html
    assert "Bronnen" in html
    assert "9.2308" in html or "9,2308" in html
    assert "WGA-premie werknemer (%)" in html
    assert 'value="0.808"' in html
    assert "pensioenfondsdetailhandel.nl" in html
    assert "wit_mnd_nl_std_20260101.pdf" in html
    assert 'name="achteraf_' not in html
    token = csrf_uit(html)
    data = {"csrf_token": token, "actie": "opslaan"}
    # De twee gezaaide perioden terugsturen, met een uurloon op de eerste.
    for index, rij in enumerate(opslag.perioden_dicts()):
        periode = periode_uit_dict(rij)
        data[f"naam_{index}"] = rij["naam"]
        data[f"geldig_vanaf_{index}"] = rij["geldig_vanaf"]
        data[f"geldig_tot_{index}"] = rij["geldig_tot"]
        data[f"uren_per_week_{index}"] = rij["uren_per_week"]
        data[f"uurloon_{index}"] = "15" if index == 0 else ""
        data[f"flex_verlof_percentage_{index}"] = rij["flex_verlof_percentage"]
        data[f"vakantiegeld_percentage_{index}"] = rij["vakantiegeld_percentage"]
        data[f"pensioen_percentage_{index}"] = rij["pensioen_percentage"]
        data[f"jaarfranchise_{index}"] = rij["jaarfranchise"]
        data[f"fulltime_uren_per_week_{index}"] = rij["fulltime_uren_per_week"]
        data[f"wga_percentage_{index}"] = rij["wga_percentage"]
        data[f"avond_vanaf_{index}"] = rij["avond_vanaf"]
        data[f"avond_percentage_{index}"] = rij["avond_percentage"]
        data[f"zondag_percentage_{index}"] = rij["zondag_percentage"]
        data[f"zaterdag_percentage_{index}"] = rij["zaterdag_percentage"]
        data[f"nacht_tot_{index}"] = rij["nacht_tot"]
        data[f"nacht_percentage_{index}"] = rij["nacht_percentage"]
        data[f"zaterdag_vanaf_{index}"] = rij["zaterdag_vanaf"]
        data[f"feestdag_percentage_{index}"] = rij["feestdag_percentage"]
        data[f"overwerk_daguren_{index}"] = rij["overwerk_daguren"]
        data[f"overwerk_weekuren_{index}"] = rij["overwerk_weekuren"]
        data[f"overwerk_weken_{index}"] = rij["overwerk_weken"]
        data[f"overwerk_eerste_uren_{index}"] = rij["overwerk_eerste_uren"]
        data[f"overwerk_eerste_percentage_{index}"] = rij["overwerk_eerste_percentage"]
        data[f"overwerk_daarna_percentage_{index}"] = rij["overwerk_daarna_percentage"]
        if rij["overwerk"]:
            data[f"overwerk_{index}"] = "ja"
        if periode.all_in:
            data[f"all_in_{index}"] = "ja"
        if periode.vakantiegeld_maandelijks:
            data[f"vakantiegeld_maandelijks_{index}"] = "ja"
        if periode.vast_maandloon:
            data[f"vast_maandloon_{index}"] = "ja"
    antwoord = client.post("/instellingen/perioden", data=data, headers=INGRESS, follow_redirects=True)
    assert antwoord.status_code == 200
    assert opslag.perioden_dicts()[0]["uurloon"] == "15"
    assert opslag.perioden_dicts()[1]["uurloon"] == ""
    assert opslag.perioden_dicts()[1]["vast_maandloon"] is True
    assert opslag.perioden_dicts()[0]["vast_maandloon"] is False
    maand = client.get("/?maand=2026-10", headers=INGRESS).get_data(as_text=True)
    assert "15,00" in maand or "€ 15,00" in maand


def test_instellingen_passen_op_een_smal_scherm(client):
    """iOS geeft een datumveld een eigen minimumbreedte. De stylesheet moet
    die breedte breken, de waarde links zetten, en in de zijbalk geen extra
    strook boven de balk laten.
    """
    layout = (ROOT / "rooster_app" / "app" / "templates" / "_layout.html").read_text(encoding="utf-8")
    assert "minmax(0, 1fr)" in layout
    assert "::-webkit-date-and-time-value" in layout
    assert "text-align: left" in layout
    assert "body.in-ingress .balk" in layout
    assert "-webkit-appearance: none" in layout
    assert "appearance: none" in layout
    assert '<html lang="nl">' in layout
    assert "align-items: end" in layout
    instellingen = (ROOT / "rooster_app" / "app" / "templates" / "instellingen.html").read_text(encoding="utf-8")
    assert 'placeholder="leeg"' in instellingen
    assert "overgenomen van de vorige periode" in instellingen
    assert "Flexverlof (%)" in instellingen
    assert "Flexverlof uitbetalen" not in instellingen
    html = client.get("/instellingen", headers=INGRESS).get_data(as_text=True)
    assert 'class="in-ingress"' in html
    assert 'placeholder="leeg"' in html
    assert 'placeholder="nu' not in html
    maand = client.get("/", headers=INGRESS).get_data(as_text=True)
    assert 'class="in-ingress"' in maand
    buiten = client.get("/instellingen")
    assert buiten.status_code == 403
    assert 'class="in-ingress"' not in buiten.get_data(as_text=True)


def test_versie_in_config_en_code_zijn_dezelfde():
    import main

    tekst = (ROOT / "rooster_app" / "config.yaml").read_text(encoding="utf-8")
    assert f'version: "{main.VERSIE}"' in tekst


def test_ingress_blijft_op_de_standaardpoort_zonder_open_poort():
    """8099 is de standaard ingress-poort. Die niet herhalen in config.yaml,
    anders wijst de add-on linter hem af. De app moet daar wel op luisteren.
    Een gepubliceerde poort was er voor de agendalink; die is weg. De
    smoke-test mapt 8099 alleen om de zijbalk te kunnen bereiken.
    """
    config = (ROOT / "rooster_app" / "config.yaml").read_text(encoding="utf-8")
    zonder_commentaar = "\n".join(regel.split("#", 1)[0] for regel in config.splitlines())
    assert "ingress: true" in zonder_commentaar
    assert "ingress_port" not in zonder_commentaar
    assert "ports:" not in zonder_commentaar
    assert "ports_description" not in zonder_commentaar
    script = (ROOT / "rooster_app" / "rootfs" / "usr" / "bin" / "rooster-app").read_text(encoding="utf-8")
    assert 'export PORT="8099"' in script
    app = (ROOT / "rooster_app" / "app" / "main.py").read_text(encoding="utf-8")
    assert 'os.environ.get("PORT", "8099")' in app
    smoke = (ROOT / ".github" / "workflows" / "build.yaml").read_text(encoding="utf-8")
    assert "8099:8099" in smoke
    assert "localhost:8099" in smoke
    assert "X-Ingress-Path" in smoke
    assert "kale poort" not in smoke
    assert "agendafeed" not in smoke


def test_ingress_alleen_het_proxy_adres():
    from main import STANDAARD_INGRESS, afzender_mag, netwerken_uit

    assert STANDAARD_INGRESS == "172.30.32.2"
    netwerken = netwerken_uit(STANDAARD_INGRESS)
    assert afzender_mag("172.30.32.2", netwerken)
    assert not afzender_mag("172.30.32.1", netwerken)
    assert not afzender_mag("172.30.32.3", netwerken)
    assert not afzender_mag("172.30.33.2", netwerken)
    bron = (ROOT / "rooster_app" / "app" / "main.py").read_text(encoding="utf-8")
    assert 'STANDAARD_INGRESS = "172.30.32.2"' in bron
    assert 'ip_network("172.30.32.0/23")' not in bron


def test_onbekend_jaar_noemt_de_gebruikte_tabellen(client):
    rij = standaard_periode_dicts()[1]
    rij["uurloon"] = "20"
    rij["geldig_vanaf"] = "2026-01-01"
    opslag.vervang_perioden([rij])
    for periode_id, naam, van, tot in (
        (1, "oktober 2026", date(2026, 10, 1), date(2026, 10, 31)),
        (2, "mei 2027", date(2027, 5, 1), date(2027, 5, 31)),
    ):
        opslag.bewaar_samenvatting({
            "periode_id": periode_id,
            "naam": naam,
            "van": van,
            "tot": tot,
            "jaar": van.year,
            "gerealiseerd_minuten": 100 * 60,
            "compensatie_minuten": 0,
            "plusmin_minuten": 0,
            "verlof_minuten": 0,
            "toeslagen": 0,
        })
    html = client.get("/?maand=2027-05", headers=INGRESS).get_data(as_text=True)
    assert "tabellen van 2026" in html
    assert "Twee maanden in één uitbetaling" not in html
    assert "Uitbetaald in" not in html
    assert "niet meegeteld in het netto" in html


def test_oude_database_laat_de_uitbetaalmaand_vallen():
    with opslag.verbinding() as conn:
        conn.execute("ALTER TABLE contractperioden ADD COLUMN achteraf INTEGER")
        conn.execute("UPDATE contractperioden SET achteraf = 1 WHERE naam = 'Hulpkracht'")
    opslag.init_db()
    with opslag.verbinding() as conn:
        kolommen = {rij[1] for rij in conn.execute("PRAGMA table_info(contractperioden)")}
    assert "achteraf" not in kolommen
    rijen = opslag.perioden_dicts()
    assert rijen[0]["naam"] == "Hulpkracht"
    assert "achteraf" not in rijen[0]
    assert rijen[1]["vast_maandloon"] is True


def test_loonschaal_blijft_in_de_gegevens_en_vult_een_leeg_uurloon(client):
    pagina = client.get("/instellingen", headers=INGRESS)
    token = csrf_uit(pagina.get_data(as_text=True))
    antwoord = client.post(
        "/instellingen/loonschaal",
        data={"csrf_token": token, "geboortedatum": "2006-04-01", "loonschaal": "2"},
        headers=INGRESS,
        follow_redirects=True,
    )
    assert antwoord.status_code == 200
    assert opslag.meta_get("geboortedatum") == "2006-04-01"
    assert opslag.meta_get("loonschaal") == "2"
    from datetime import date as datum

    from main import vandaag
    from salaris import cao_uurloon

    voorstel = cao_uurloon(datum(2006, 4, 1), "2", vandaag().year, vandaag().month)
    tekst = antwoord.get_data(as_text=True)
    assert voorstel is not None
    assert _euro(voorstel) in tekst
    maand = client.get("/?maand=2026-10", headers=INGRESS).get_data(as_text=True)
    assert "12,24" in maand
    assert "volgens de cao-schaal" in maand
    for pad in (ROOT / "rooster_app" / "app").rglob("*.py"):
        assert "2006-04-01" not in pad.read_text(encoding="utf-8")


def test_oude_standaardregels_worden_eenmalig_de_cao():
    opslag.meta_set("cao_2026_regels", None)
    with opslag.verbinding() as conn:
        conn.execute(
            """
            UPDATE contractperioden
            SET flex_verlof_percentage = '9.23', avond_vanaf = '18:00',
                zaterdag_percentage = '0', zondag_percentage = '50'
            WHERE naam = 'Hulpkracht'
            """
        )
        conn.execute(
            """
            UPDATE contractperioden
            SET avond_vanaf = '19:00', zaterdag_percentage = '25', zondag_percentage = '50'
            WHERE naam = 'Parttime verkoopmedewerker'
            """
        )
    opslag.init_db()
    rijen = {rij["naam"]: rij for rij in opslag.perioden_dicts()}
    assert rijen["Hulpkracht"]["flex_verlof_percentage"] == "9.2308"
    assert rijen["Hulpkracht"]["avond_vanaf"] == "21:00"
    assert rijen["Hulpkracht"]["zaterdag_percentage"] == "50"
    assert rijen["Hulpkracht"]["nacht_tot"] == "06:00"
    assert rijen["Parttime verkoopmedewerker"]["avond_vanaf"] == "19:00"
    assert rijen["Parttime verkoopmedewerker"]["zaterdag_percentage"] == "25"
    with opslag.verbinding() as conn:
        conn.execute(
            """
            UPDATE contractperioden
            SET avond_vanaf = '18:00', zaterdag_percentage = '0', zondag_percentage = '50'
            WHERE naam = 'Hulpkracht'
            """
        )
    opslag.init_db()
    assert opslag.perioden_dicts()[0]["avond_vanaf"] == "18:00"


def test_maand_toont_dienst_en_deeldagverlof_apart(client):
    from agenda import uid_dienst

    opslag.bewaar_diensten([{
        "datum": date(2026, 12, 1),
        "start_minuten": 9 * 60,
        "eind_minuten": 18 * 60,
        "pauze_minuten": 0,
        "totaal_minuten": 9 * 60,
        "winkel": "Bouwmarkt Voorbeeld",
        "winkel_code": "BV01",
        "afdeling": "Verkoop",
        "afdeling_code": "07",
        "afdeling_id": 3,
        "pauzes": [],
        "uniek": uid_dienst(date(2026, 12, 1), "1"),
    }])
    opslag.vervang_verlof_van_jaren([2026], [{
        "van": date(2026, 12, 1),
        "tot": date(2026, 12, 1),
        "code": "V",
        "omschrijving": "",
        "memo": "",
        "soort": "Vakantie",
        "gedeeltelijk": True,
        "van_minuten": 18 * 60,
        "tot_minuten": 23 * 60 + 59,
        "uniek": "verlof-id-42@rooster-app",
    }])
    html = client.get("/?maand=2026-12", headers=INGRESS).get_data(as_text=True)
    assert "09:00–18:00" in html
    assert "Vrij vanaf 18:00" in html


def test_instellingen_toont_geen_tarief_uit_het_rooster(client):
    html = client.get("/instellingen", headers=INGRESS).get_data(as_text=True)
    assert "Overnemen" not in html
    assert "per uur vanaf" not in html


def test_geheim_staat_vanaf_het_aanmaken_op_0600():
    import os

    oud = os.umask(0)
    try:
        opslag.schrijf_geheim("voorbeeld", "niet-echt")
        modus = os.stat(opslag.GEHEIM_PATH).st_mode & 0o777
    finally:
        os.umask(oud)
    assert modus == 0o600
