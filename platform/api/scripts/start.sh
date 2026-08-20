#!/bin/bash
echo 'Starting blue-data-user api...'

# start (bind to all interfaces by default; override with UDB_HOST if needed)
UDB_HOST="${UDB_HOST:-0.0.0.0}" udb-api
