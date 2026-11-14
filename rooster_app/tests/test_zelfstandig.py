"""De losse modus (docker compose op de Pi): een eigen wachtwoord in plaats
van de zijbalk van Home Assistant."""
from __future__ import annotations

import os
import pathlib
import stat

import pytest

import main
from conftest import INGRESS, csrf_uit

WACHTWOORD = "verzonnen-wachtwoord"


@pytest.fixture
def zelfstandig(monkeypatch):
    monkeypatch.setattr(main, "ZELFSTANDIG", True)
    monkeypatch.setattr(main, "INGRESS_NETWERKEN", [])
    main.app.jinja_env.globals["zelfstandig"] = True
    yield
    main.app.jinja_env.globals["zelfstandig"] = False


def _kies_wachtwoord(client, wachtwoord=WACHTWOORD, nogmaals=None):
    token = csrf_uit(client.get("/inloggen").get_data(as_text=True))
    return client.post("/inloggen", data={
        "csrf_token": token, "wachtwoord": wachtwoord,
        "nogmaals": wachtwoord if nogmaals is None else nogmaals,
    })


def _log_in(client, wachtwoord=WACHTWOORD):
    token = csrf_uit(client.get("/inloggen").get_data(as_text=True))
    return client.post("/inloggen", data={"csrf_token": token, "wachtwoord": wachtwoord})


def test_zonder_wachtwoord_stuurt_elke_pagina_naar_inloggen(client, zelfstandig):
    for pad in ["/", "/saldo", "/verlof", "/instellingen"]:
        antwoord = client.get(pad)
        assert antwoord.status_code == 302
        assert antwoord.headers["Location"].endswith("/inloggen")


def test_een_ingressheader_komt_niet_langs_het_wachtwoord(client, zelfstandig):
    antwoord = client.get("/", headers=INGRESS)
    assert antwoord.status_code == 302
    assert antwoord.headers["Location"].endswith("/inloggen")


def test_de_eerste_keer_kies_je_een_wachtwoord_en_ben_je_binnen(client, zelfstandig):
    html = client.get("/inloggen").get_data(as_text=True)
    assert "Kies een wachtwoord" in html
    assert 'href="/instellingen"' not in html  # geen menu vóór het inloggen

    antwoord = _kies_wachtwoord(client)
    assert antwoord.headers["Location"].endswith("/")
    assert client.get("/").status_code == 200

    pad = pathlib.Path(main.TOEGANG_PATH)
    assert WACHTWOORD not in pad.read_text()
    assert stat.S_IMODE(os.stat(pad).st_mode) == 0o600


def test_een_te_kort_of_verschillend_wachtwoord_wordt_niet_bewaard(client, zelfstandig):
    _kies_wachtwoord(client, "kort")
    _kies_wachtwoord(client, WACHTWOORD, nogmaals="iets-anders-123")
    assert not pathlib.Path(main.TOEGANG_PATH).exists()
    assert client.get("/").status_code == 302


def test_inloggen_met_het_goede_wachtwoord_en_weer_uitloggen(client, zelfstandig):
    _kies_wachtwoord(client)
    with main.app.test_client() as ander:
        _log_in(ander, "fout-wachtwoord")
        assert ander.get("/").status_code == 302
        _log_in(ander)
        html = ander.get("/instellingen").get_data(as_text=True)
        assert "Uitloggen" in html
        ander.post("/uitloggen", data={"csrf_token": csrf_uit(html)})
        assert ander.get("/").status_code == 302


def test_na_vijf_foute_pogingen_helpt_ook_het_goede_wachtwoord_even_niet(client, zelfstandig):
    _kies_wachtwoord(client)
    with main.app.test_client() as ander:
        for _ in range(main.MAX_POGINGEN):
            _log_in(ander, "fout-wachtwoord")
        _log_in(ander)
        assert ander.get("/").status_code == 302
        assert "Te veel mislukte pogingen" in ander.get("/inloggen").get_data(as_text=True)


def test_toegang_json_wissen_logt_iedereen_uit(client, zelfstandig):
    _kies_wachtwoord(client)
    assert client.get("/").status_code == 200
    pathlib.Path(main.TOEGANG_PATH).unlink()
    antwoord = client.get("/")
    assert antwoord.status_code == 302
    assert "Kies een wachtwoord" in client.get("/inloggen").get_data(as_text=True)


def test_in_home_assistant_bestaat_de_inlogpagina_niet(client):
    assert client.get("/inloggen", headers=INGRESS).status_code == 404


def test_de_cookie_heeft_een_eigen_naam_naast_de_facturen_app():
    assert main.app.config["SESSION_COOKIE_NAME"] == "rooster_app_session"


def test_een_tikfout_in_zelfstandig_start_de_app_niet(monkeypatch):
    monkeypatch.setenv("ZELFSTANDIG", "jaa")
    with pytest.raises(SystemExit):
        main.schakelaar("ZELFSTANDIG")


def test_compose_zet_de_losse_modus_vast_en_kiest_poort_8100():
    hoofdmap = pathlib.Path(__file__).resolve().parents[2]
    compose = (hoofdmap / "docker-compose.yml").read_text()
    assert 'ZELFSTANDIG: "1"' in compose
    assert "${POORT:-8100}" in compose
    assert "POORT=8100" in (hoofdmap / ".env.example").read_text()
