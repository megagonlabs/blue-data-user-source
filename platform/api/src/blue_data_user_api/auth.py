"""The family's HTTP policy, from blue_data.server (blue-data#116, #157).

Every route that reads or changes a user's data carries ``SECURITY``:

- an API key, required by default: ``BLUE_DATA_USER_API_KEY``, sent as
  ``X-API-Key`` or ``Authorization: Bearer``; without one configured, requests
  get 401 unless ``BLUE_DATA_USER_API_AUTH_DISABLED=true``;
- a CSRF guard: a state-changing request with a form, multipart or text body
  (what a cross-site HTML form can send) gets 415.

The two routes a person or a mail provider reaches from outside, the reply form
an email links to and the inbound-email webhook, do not carry it: neither can
send a key, and the interaction id in their URL or address is the credential.
"""
from __future__ import annotations

from fastapi import Depends
from blue_data.server import make_api_key_guard, make_csrf_guard

ENV_PREFIX = "BLUE_DATA_USER_API"
DEFAULT_PORT = 8003  # the family port map: registry 8000, doc 8001, web 8002, user 8003

require_api_key = make_api_key_guard(ENV_PREFIX)
require_json_writes = make_csrf_guard()

SECURITY = [Depends(require_api_key), Depends(require_json_writes)]
