#!/bin/bash
echo 'Starting blue-data-user api...'

# start (bind to all interfaces by default; override with BLUE_DATA_USER_SOURCE_HOST if needed)
BLUE_DATA_USER_SOURCE_HOST="${BLUE_DATA_USER_SOURCE_HOST:-0.0.0.0}" blue-userdb-api
