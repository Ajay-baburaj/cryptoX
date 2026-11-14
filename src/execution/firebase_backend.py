"""Firebase pieces that need Google, without a service-account key file (same approach as the Nifty app).

* Sign-in: a Firebase ID token is verified against Google's public keys (signature, expiry, issuer and
  audience = the Firebase project id). No Admin credentials are involved.
* Push: Firebase Cloud Messaging HTTP v1, sent with the machine's default Google credentials (a VM's
  service account with the "Firebase Cloud Messaging Admin" role, or ``gcloud auth application-default
  login`` on a laptop). With no usable credentials sending is skipped with one log line, never an error.
"""
from __future__ import annotations

import logging

import google.auth
import google.auth.transport.requests
import requests
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import id_token

LOG = logging.getLogger("firebase")
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


class FirebaseBackend:
    def __init__(self, project_id: str):
        self.project_id = project_id
        self._request = google.auth.transport.requests.Request(session=requests.Session())
        self._session: AuthorizedSession | None = None
        self.push_disabled_reason = ""

    # ---- sign-in -----------------------------------------------------------------------

    def verify_id_token(self, token: str) -> dict:
        """Claims of a valid Firebase ID token for this project. Raises on any problem."""
        claims = id_token.verify_firebase_token(token, self._request, audience=self.project_id)
        if claims.get("iss") != f"https://securetoken.google.com/{self.project_id}":
            raise ValueError("Invalid Firebase token issuer")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not 1 <= len(subject) <= 128:
            raise ValueError("Invalid Firebase token subject")
        return claims

    # ---- push --------------------------------------------------------------------------

    def _authed(self) -> AuthorizedSession | None:
        if self._session is None and not self.push_disabled_reason:
            try:
                credentials, _ = google.auth.default(scopes=[SCOPE])
                self._session = AuthorizedSession(credentials)
            except Exception as exc:  # no credentials on this machine
                self.push_disabled_reason = str(exc)
                LOG.info("push notifications off: %s", exc)
        return self._session

    def send_push(self, tokens: list[str], data: dict[str, str]) -> dict:
        """Count FCM acceptances separately from failures; acceptance is not device delivery."""
        result = {"sent": 0, "failed": 0, "dead": []}
        session = self._authed()
        if session is None or not tokens:
            result["failed"] = len(tokens)
            return result
        url = f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send"
        for token in tokens:
            body = {"message": {"token": token, "data": {k: str(v) for k, v in data.items()},
                                "webpush": {"headers": {"Urgency": "high", "TTL": "3600"}}}}
            try:
                response = session.post(url, json=body, timeout=10)
            except Exception as exc:
                LOG.warning("push send failed: %s", exc)
                result["failed"] += 1
                continue
            if response.status_code == 200:
                result["sent"] += 1
                continue
            result["failed"] += 1
            try:
                details = response.json().get("error", {}).get("details", [])
            except ValueError:
                details = []
            if any(d.get("@type") == "type.googleapis.com/google.firebase.fcm.v1.FcmError"
                   and d.get("errorCode") == "UNREGISTERED" for d in details):
                result["dead"].append(token)
            LOG.warning("push rejected: HTTP %s", response.status_code)
        return result
