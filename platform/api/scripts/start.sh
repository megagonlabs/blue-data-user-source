#!/bin/bash
echo 'Starting blue-data-user api...'

# start (bind to all interfaces by default; override with BLUE_DATA_USER_API_HOST if needed).
# The API key is required: set BLUE_DATA_USER_API_KEY (or BLUE_DATA_USER_API_AUTH_DISABLED=true).
BLUE_DATA_USER_API_HOST="${BLUE_DATA_USER_API_HOST:-0.0.0.0}" blue-userdb-api
