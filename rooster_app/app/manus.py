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
    def __init__(self, bericht: str, status: int | None = None, inhoud=None):
        super().__init__(bericht)
        self.status = status
        # De ruwe servertekst blijft hier, buiten de melding aan de gebruiker.
        # De sync herkent daaraan een jaar zonder afgesloten periodes.
        self.inhoud = inhoud


class AlleenLezenFout(ManusFout):
    pass


class _GeenAutomatischeRedirect(urllib.request.HTTPRedirectHandler):
    """urlopen volgt anders zelf, en stuurt Authorization naar de nieuwe host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _manus_url(url: str) -> bool:
    stuk = urllib.parse.urlparse(url)
    host = (stuk.hostname or "").lower()
    return stuk.scheme == "https" and host == "server.manus.plus"


def _koppen(headers) -> dict:
    if headers is None:
        return {}
    return {str(sleutel): str(waarde) for sleutel, waarde in headers.items()}


def _autorisatie(headers: dict) -> str | None:
    for sleutel, waarde in headers.items():
        if sleutel.lower() == "authorization":
            return waarde
    return None


def _zonder_autorisatie(headers: dict) -> dict:
    return {
        sleutel: waarde
        for sleutel, waarde in headers.items()
        if sleutel.lower() != "authorization"
    }


def volg_redirects(verstuur, methode: str, url: str, headers: dict, body: bytes | None, toegestaan, foutklasse, max_sprongen: int = 5):
    """Volg doorverwijzingen zelf. Het token gaat alleen naar een toegestane host.

    urllib stuurt Authorization mee bij elke sprong. Dat willen we niet:
    een andere host krijgt het token niet, en de body van het inloggen ook
    niet. Blijft het doel toegestaan, dan zetten we het token opnieuw.
    """
    token = _autorisatie(headers)
    basis = _zonder_autorisatie(headers)
    huidige = methode
    lading = body
    for _sprong in range(max_sprongen + 1):
        if not toegestaan(url):
            raise foutklasse("Die doorverwijzing gaat niet naar de bekende server.")
        te_sturen = dict(basis)
        if token and toegestaan(url):
            te_sturen["Authorization"] = token
        status, koppen, ruw = verstuur(huidige, url, te_sturen, lading)
        if status not in (301, 302, 307, 308):
            return status, koppen, ruw
        doel = None
        for sleutel, waarde in (koppen or {}).items():
            if str(sleutel).lower() == "location":
                doel = waarde
                break
        if not doel:
            raise foutklasse("De server stuurde een doorverwijzing zonder adres.", status)
        volgend = urllib.parse.urljoin(url, doel)
        if not toegestaan(volgend):
            raise foutklasse("Die doorverwijzing gaat niet naar de bekende server.")
        # 301 en 302 horen bij een POST geen body meer mee te nemen.
        if status in (301, 302) and huidige not in ("GET", "HEAD"):
            huidige = "GET"
            lading = None
        url = volgend
    raise foutklasse("De server stuurde te veel doorverwijzingen.")


def _een_keer(methode: str, url: str, headers: dict, body: bytes | None, timeout: float):
    opener = urllib.request.build_opener(_GeenAutomatischeRedirect)
    verzoek = urllib.request.Request(url, data=body, headers=headers, method=methode)
    try:
        with opener.open(verzoek, timeout=timeout) as antwoord:
            return antwoord.status, _koppen(antwoord.headers), antwoord.read()
    except urllib.error.HTTPError as fout:
        return fout.code, _koppen(fout.headers), fout.read()


def standaard_opener(methode: str, url: str, headers: dict, body: bytes | None, timeout: float):
    def verstuur(huidige, doel, te_sturen, lading):
        return _een_keer(huidige, doel, te_sturen, lading, timeout)

    try:
        status, _koppen_antwoord, ruw = volg_redirects(
            verstuur, methode, url, headers, body, _manus_url, ManusFout
        )
    except urllib.error.URLError as fout:
        raise ManusFout("MyManus is niet bereikbaar. Probeer het later opnieuw.") from fout
    return status, ruw


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
        # De fouttekst van de server niet doorgeven. Wel de json bewaren:
        # een jaar zonder afgesloten periodes is een herkenbare code, geen storing.
        inhoud = _json_zacht(ruw) if status >= 400 else None
        if status == 401:
            raise ManusFout("De sessie bij MyManus is verlopen.", 401, inhoud)
        if status == 404:
            raise ManusFout("MyManus kent dit adres niet.", 404, inhoud)
        if status >= 400:
            raise ManusFout(f"MyManus antwoordde met een fout ({status}).", status, inhoud)
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


def _json_zacht(ruw: bytes):
    """Foutantwoorden zijn niet altijd json. Dan is er niets te herkennen."""
    if not ruw:
        return None
    try:
        return json.loads(ruw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
