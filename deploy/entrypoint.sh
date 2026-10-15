#!/bin/sh
# First start: creates the master key, the database and the first admin
# (its one-time password is printed in `docker compose logs rushd`).
# Later starts: does nothing but check that the key works.
set -eu
python -m rushd init
exec python -m rushd serve --host 0.0.0.0 --port 8000 --forwarded-allow-ips "${RUSHD_FORWARDED_ALLOW_IPS:-*}"
