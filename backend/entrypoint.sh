#!/bin/sh
# Make sure the quadstore exists before the API starts.
#
# The 1.2 GB store is not in the image. On a fresh volume this fetches it
# once; on every subsequent boot the file is already there and this is a
# no-op, so the cost is paid per volume, not per deploy.
set -eu

if [ -f "$ESCO_STORE" ]; then
    echo "entrypoint: quadstore present at $ESCO_STORE"
    exec "$@"
fi

if [ -z "${ESCO_STORE_URL:-}" ]; then
    echo "entrypoint: FATAL - $ESCO_STORE is missing and ESCO_STORE_URL is unset." >&2
    echo "entrypoint: either set ESCO_STORE_URL, or put esco.sqlite3 on the volume." >&2
    exit 1
fi

echo "entrypoint: quadstore missing, fetching $ESCO_STORE_URL"
tmp="${ESCO_STORE}.partial"
rm -f "$tmp"

# Decompressed straight from the stream, so the 415 MB archive never lands on
# disk and the volume only needs room for the 1.2 GB store itself.
# --retry covers a flaky link on a 400 MB download; the progress meter is
# off because it writes thousands of lines into the container log.
curl -fsSL --no-progress-meter --retry 3 --retry-delay 5 "$ESCO_STORE_URL" | zstd -d -o "$tmp"

# /bin/sh here is dash, which has no `pipefail`, so a curl failure mid-stream
# would not fail the pipeline on its own. Check the result really is a SQLite
# database rather than trusting the exit status.
if [ "$(head -c 15 "$tmp")" != "SQLite format 3" ]; then
    echo "entrypoint: FATAL - download did not produce a SQLite database." >&2
    rm -f "$tmp"
    exit 1
fi

# Rename only once it is known-good: an interrupted run leaves .partial
# behind and retries, never a truncated file the app would open as valid.
mv "$tmp" "$ESCO_STORE"
echo "entrypoint: quadstore ready ($(du -h "$ESCO_STORE" | cut -f1))"

exec "$@"
