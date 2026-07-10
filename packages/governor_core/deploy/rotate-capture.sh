#!/bin/sh
# rotate-capture.sh — R-D16 retention (docs/RETENTION.md): ground, then rotate +
# compress the raw capture, then prune archives past the retention window.
#
# Ground-before-rotate is the load-bearing order: rotation must never destroy
# ungrounded evidence. The rename is atomic and the daemon opens the capture file
# per append, so the next gated call recreates it; no daemon restart needed.
set -eu

DIR="${CREDENCE_GOVERNOR_DIR:-$HOME/.credence-governor}"
RAW="$DIR/raw_events.jsonl"
KEEP_DAYS="${CREDENCE_GOVERNOR_RAW_RETENTION_DAYS:-90}"
# The daemon's own environment (the uv tool venv) so grounding sees the same code.
GROUND_PYTHON="${CREDENCE_GOVERNOR_GROUND_PYTHON:-$HOME/.local/share/uv/tools/credence-governor-core/bin/python}"

[ -s "$RAW" ] || { echo "rotate-capture: no raw capture at $RAW; pruning only"; \
  find "$DIR" -maxdepth 1 -name 'raw_events-*.jsonl.zst' -mtime +"$KEEP_DAYS" -delete; exit 0; }

echo "rotate-capture: grounding $RAW before rotation"
"$GROUND_PYTHON" -m credence_governor_core.training.ground_capture --capture "$RAW"

stamp=$(date +%Y%m%d-%H%M%S)
mv "$RAW" "$DIR/raw_events-$stamp.jsonl"
echo "rotate-capture: compressing raw_events-$stamp.jsonl"
zstd -T0 -q --rm "$DIR/raw_events-$stamp.jsonl" -o "$DIR/raw_events-$stamp.jsonl.zst"

find "$DIR" -maxdepth 1 -name 'raw_events-*.jsonl.zst' -mtime +"$KEEP_DAYS" -delete
echo "rotate-capture: done (window ${KEEP_DAYS}d)"
