"""Read-only client voor MyManus (MANUS Workforce Management, tenant intergamma).

Alleen de token-aanvraag is een POST. Al het andere is een GET. Een PUT of
een andere POST wijst de client zelf af, nog vóór er iets het netwerk op
gaat: dit is een persoonlijk overzicht, geen manier om het rooster te wijzigen.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

API_BASIS = "https://server.manus.plus/intergamma/api/"
TOKEN_URL = "https://server.manus.plus/intergamma/app/token"
ACCEPTEER = "application/vnd.manusplus+json"


class ManusFout(Exception):
    def __init__(self, bericht: str, status: int | None = None):
        super().__init__(bericht)
        self.status = status


class AlleenLezenFout(ManusFout):
    pass


def standaard_opener(methode: str, url: str, headers: dict, body: bytes | None, timeout: float):
    verzoek = urllib.request.Request(url, data=body, headers=headers, method=methode)
    try:
        with urllib.request.urlopen(verzoek, timeout=timeout) as antwoord:
            return antwoord.status, antwoord.read()
    except urllib.error.HTTPError as fout:
        return fout.code, fout.read()
    except urllib.error.URLError as fout:
        raise ManusFout("MyManus is niet bereikbaar. Probeer het later opnieuw.") from fout


class ManusClient:
    def __init__(self, opener=None, timeout: float = 20):
        self._opener = opener or standaard_opener
        self._timeout = timeout
        self.token: str | None = None

    def login(self, gebruikersnaam: str, wachtwoord: str) -> dict:
        body = urllib.parse.urlencode({
            "client_id": "employee",
            "grant_type": "password",
            "username": gebruikersnaam,
            "password": wachtwoord,
        }).encode()
        status, ruw = self._verzoek(
            "POST",
            TOKEN_URL,
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "X-Application-Type": "employee",
            },
            body,
        )
        data = _json(ruw)
        if status != 200 or not isinstance(data, dict) or not data.get("access_token"):
            # De fouttekst van de server niet doorgeven: die kan, afhankelijk
            # van de installatie, meer vertellen dan nodig is. Het wachtwoord
            # zit in elk geval niet in onze eigen melding.
            raise ManusFout("MyManus weigerde de gebruikersnaam of het wachtwoord.", status)
        self.token = data["access_token"]
        return data

    def get_json(self, pad: str):
        if not self.token:
            raise ManusFout("Er is geen sessie. Eerst inloggen.")
        status, ruw = self._verzoek(
            "GET",
            _url(pad),
            {
                "Authorization": f"Bearer {self.token}",
                "Accept": ACCEPTEER,
                "X-Application-Type": "employee",
            },
            None,
        )
        if status == 401:
            raise ManusFout("De sessie bij MyManus is verlopen.", 401)
        if status == 404:
            raise ManusFout("MyManus kent dit adres niet.", 404)
        if status >= 400:
            raise ManusFout(f"MyManus antwoordde met een fout ({status}).", status)
        if not ruw:
            return None
        return _json(ruw)

    def _verzoek(self, methode: str, url: str, headers: dict, body: bytes | None):
        if methode == "POST" and url != TOKEN_URL:
            raise AlleenLezenFout("Alleen het inloggen mag iets sturen; de rest blijft lezen.")
        if methode not in ("GET", "POST"):
            raise AlleenLezenFout("Deze app schrijft niets terug naar MyManus.")
        return self._opener(methode, url, headers, body, self._timeout)


def _url(pad: str) -> str:
    if pad.startswith("https://"):
        return pad
    return API_BASIS + pad.lstrip("/")


def _json(ruw: bytes):
    try:
        return json.loads(ruw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as fout:
        raise ManusFout("MyManus stuurde geen leesbaar antwoord.") from fout
