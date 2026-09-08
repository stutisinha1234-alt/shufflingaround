"""Thin client for the Amadeus Self-Service Flight Offers Search API.

Deliberately points at the PRODUCTION host (test.api.amadeus.com serves a
cached fare subset that's unrepresentative of real prices). Production is
still free under the self-service tier's monthly quota; it just requires a
card on file with Amadeus. Auth is OAuth2 client-credentials, read from
env vars so no secret ever lands in config.json or git history.

Southwest is not reachable through Amadeus, or any GDS, at any tier --
Southwest doesn't distribute fares through GDS channels at all. Callers
should route southwest_only_airports (see config.json) to a deep link
instead of a search call; see track.py.
"""
from __future__ import annotations

import os
import time
import urllib.error
import urllib.parse
import urllib.request
import json
from datetime import date

PROD_HOST = "https://api.amadeus.com"
TOKEN_PATH = "/v1/security/oauth2/token"
OFFERS_PATH = "/v2/shopping/flight-offers"


class AmadeusError(RuntimeError):
    pass


class AmadeusClient:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None):
        self.client_id = client_id or os.environ.get("AMADEUS_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("AMADEUS_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            raise AmadeusError(
                "AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET not set. "
                "Create a production self-service app at "
                "https://developers.amadeus.com and export both."
            )
        self._token: str | None = None
        self._token_expiry: float = 0.0

    def _request(self, method: str, path: str, *, data: bytes | None = None,
                 headers: dict | None = None) -> dict:
        req = urllib.request.Request(
            PROD_HOST + path, data=data, method=method, headers=headers or {}
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise AmadeusError(f"{method} {path} -> HTTP {e.code}: {body}") from e

    def _authenticate(self) -> str:
        if self._token and time.time() < self._token_expiry - 30:
            return self._token
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        ).encode()
        resp = self._request(
            "POST",
            TOKEN_PATH,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self._token = resp["access_token"]
        self._token_expiry = time.time() + resp.get("expires_in", 1799)
        return self._token

    def search_round_trip(
        self,
        origin: str,
        destination: str,
        depart: date,
        ret: date,
        *,
        adults: int = 1,
        max_results: int = 10,
        currency: str = "USD",
    ) -> list[dict]:
        """Returns a list of offers, each a dict with at least
        {"price": float, "carrier": str, "raw": <full offer>}, cheapest
        first. Empty list means no offers found for that origin/dest/date
        combination (not necessarily an error)."""
        token = self._authenticate()
        params = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": depart.isoformat(),
            "returnDate": ret.isoformat(),
            "adults": str(adults),
            "currencyCode": currency,
            "max": str(max_results),
            "nonStop": "false",
        }
        query = urllib.parse.urlencode(params)
        resp = self._request(
            "GET",
            f"{OFFERS_PATH}?{query}",
            headers={"Authorization": f"Bearer {token}"},
        )
        offers = []
        for item in resp.get("data", []):
            price = float(item["price"]["grandTotal"])
            carriers = {
                seg["carrierCode"]
                for itin in item.get("itineraries", [])
                for seg in itin.get("segments", [])
            }
            offers.append(
                {"price": price, "carrier": "/".join(sorted(carriers)), "raw": item}
            )
        offers.sort(key=lambda o: o["price"])
        return offers
