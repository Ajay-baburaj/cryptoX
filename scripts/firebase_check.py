"""`make firebase-check` — verify the Firebase login and push setup before starting the server.

Checks the web config and allowlist, asks Firebase whether Authentication has been initialised for the
project, and reports whether this machine has Google credentials for sending push. ``--push`` sends a
test notification to every registered browser. Nothing is changed in Firebase.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from execution.auth import AuthConfig  # noqa: E402
from execution.push import PushStore  # noqa: E402


def auth_initialised(api_key: str) -> tuple[bool, str]:
    try:
        urllib.request.urlopen(f"https://identitytoolkit.googleapis.com/v1/projects?key={api_key}", timeout=15)
        return True, "ok"
    except urllib.error.HTTPError as exc:
        message = json.loads(exc.read() or b"{}").get("error", {}).get("message", str(exc))
        return False, message
    except Exception as exc:
        return False, str(exc)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="send a test notification to registered browsers")
    args = ap.parse_args()

    cfg = AuthConfig.from_env()  # exits with a precise list of what is missing
    project = cfg.web_config["projectId"]
    print(f"config OK: project {project}; allowed to sign in: {', '.join(sorted(cfg.allowed_emails))}")

    ok, detail = auth_initialised(cfg.web_config["apiKey"])
    if ok:
        print("Firebase Authentication: initialised")
    else:
        print(f"Firebase Authentication: NOT ready ({detail}). Open https://console.firebase.google.com/project/{project}/authentication"
              " > Get started > Sign-in method > enable Email/Password, then Users > Add user.")

    backend = cfg.backend
    if backend._authed() is None:
        print(f"push sending: off on this machine ({backend.push_disabled_reason.splitlines()[0][:120]}). "
              "Run `gcloud auth application-default login` here, or run on a VM whose service account has the "
              "'Firebase Cloud Messaging Admin' role.")
    else:
        print("push sending: Google credentials found")
    store = PushStore(ROOT / "data/paper/push_tokens.json")
    print(f"registered notification browsers: {len(store.tokens())}")
    if args.push:
        result = backend.send_push(store.tokens(), {"title": "Delta Desk test", "body": "Push notifications are working.", "tag": "ob1h-test", "url": "/"})
        dead = result["dead"]
        if dead:
            store.remove(dead)
        print(f"FCM accepted: {result['sent']}; failed: {result['failed']}; removed {len(dead)} dead token(s). Device delivery must be confirmed in the browser.")


if __name__ == "__main__":
    main()
