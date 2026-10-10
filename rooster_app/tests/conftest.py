"""Schone database per test.

DATA_DIR moet gezet zijn vóór het importeren: de app maakt bij het laden
meteen de database aan, en de tests mogen niet in /data van een add-on schrijven.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

import pytest

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_DIR))

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="rooster-tests-")
os.environ["SECRET_KEY"] = "sleutel-voor-de-tests"
os.environ["INGRESS_NETWERK"] = "127.0.0.0/8"
os.environ["ROOSTER_GEEN_ACHTERGROND"] = "1"

import main  # noqa: E402
import opslag  # noqa: E402

TABELLEN = [
    "diensten",
    "verlof",
    "periodesamenvatting",
    "verlofsaldo",
    "contractperioden",
    "meta",
]

INGRESS = {"X-Ingress-Path": "/"}


def _leeg():
    with opslag.verbinding() as conn:
        for tabel in TABELLEN:
            conn.execute(f"DELETE FROM {tabel}")
    geheim = pathlib.Path(opslag.GEHEIM_PATH)
    if geheim.exists():
        geheim.unlink()
    icloud = pathlib.Path(opslag.ICLOUD_PATH)
    if icloud.exists():
        icloud.unlink()
    opties = pathlib.Path(opslag.DATA_DIR) / "options.json"
    if opties.exists():
        opties.unlink()
    opslag.zorg_voor_standen()


@pytest.fixture(autouse=True)
def schoon():
    _leeg()
    yield
    _leeg()


@pytest.fixture
def client():
    main.app.config["TESTING"] = True
    return main.app.test_client()


def csrf_uit(html: str) -> str:
    import re

    gevonden = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert gevonden, html[:500]
    return gevonden.group(1)
