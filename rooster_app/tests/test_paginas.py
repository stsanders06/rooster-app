"""Pagina's, ingress en de dubbele uitbetaling van oktober."""
import pathlib
from datetime import date

import opslag
from conftest import INGRESS, csrf_uit
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


def test_oktober_toont_de_dubbele_uitbetaling(client):
    _perioden_met_loon()
    _september_dicht()
    _oktober_dienst()
    antwoord = client.get("/?maand=2026-10", headers=INGRESS)
    html = antwoord.get_data(as_text=True)
    assert antwoord.status_code == 200
    assert "oktober 2026" in html
    assert "gepland/geschat" in html
    assert "Twee maanden in één uitbetaling" in html
    # Zondag 10:00–16:00 is 50% toeslag. 50 mag niet als 5% op het scherm.
    assert "uur à 50%" in html
    assert "uur à 5%" not in html
    assert "Bouwmarkt Voorbeeld" in html
    assert "€" in html
    september = client.get("/?maand=2026-09", headers=INGRESS).get_data(as_text=True)
    assert "definitief" in september
    assert "80,00" in september


def test_agendafeed_werkt_zonder_ingress_en_een_verkeerde_token_niet(client):
    token = opslag.agenda_token()
    goed = client.get(f"/agenda/{token}.ics")
    assert goed.status_code == 200
    assert "text/calendar" in goed.content_type
    assert "BEGIN:VCALENDAR" in goed.get_data(as_text=True)
    fout = client.get("/agenda/dit-is-niet-de-token.ics")
    assert fout.status_code == 404


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
        data[f"achteraf_{index}"] = "ja" if periode.achteraf else "nee"
        if periode.all_in:
            data[f"all_in_{index}"] = "ja"
        if periode.vakantiegeld_maandelijks:
            data[f"vakantiegeld_maandelijks_{index}"] = "ja"
    antwoord = client.post("/instellingen/perioden", data=data, headers=INGRESS, follow_redirects=True)
    assert antwoord.status_code == 200
    assert opslag.perioden_dicts()[0]["uurloon"] == "15"
    assert opslag.perioden_dicts()[1]["uurloon"] == ""
    maand = client.get("/?maand=2026-10", headers=INGRESS).get_data(as_text=True)
    assert "15,00" in maand or "€ 15,00" in maand


def test_versie_in_config_en_code_zijn_dezelfde():
    import main

    tekst = (ROOT / "rooster_app" / "config.yaml").read_text(encoding="utf-8")
    assert f'version: "{main.VERSIE}"' in tekst


def test_ingress_blijft_op_de_standaardpoort():
    """8099 is de standaard ingress-poort. Die niet herhalen in config.yaml,
    anders wijst de add-on linter hem af. De app moet daar wel op luisteren.
    """
    config = (ROOT / "rooster_app" / "config.yaml").read_text(encoding="utf-8")
    zonder_commentaar = "\n".join(regel.split("#", 1)[0] for regel in config.splitlines())
    assert "ingress: true" in zonder_commentaar
    assert "ingress_port" not in zonder_commentaar
    script = (ROOT / "rooster_app" / "rootfs" / "usr" / "bin" / "rooster-app").read_text(encoding="utf-8")
    assert 'export PORT="8099"' in script
    app = (ROOT / "rooster_app" / "app" / "main.py").read_text(encoding="utf-8")
    assert 'os.environ.get("PORT", "8099")' in app
    smoke = (ROOT / ".github" / "workflows" / "build.yaml").read_text(encoding="utf-8")
    assert "8099:8099" in smoke
    assert "localhost:8099" in smoke


def test_rekenvoorbeeld_staat_niet_als_standaard_uurloon_in_de_app():
    tekst = (ROOT / "rooster_app" / "app" / "salaris.py").read_text(encoding="utf-8")
    # Het rekenvoorbeeld hoort in de tests, niet als vooringevuld loon.
    assert "12.24" not in tekst
    assert "12,24" not in tekst
