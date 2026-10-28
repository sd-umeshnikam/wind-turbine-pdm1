#!/bin/sh
# Fails when the console ships invented data: mock/dummy/fake/sample data, random
# numbers or bundled JSON fixtures. Every number on screen must come from the API.
# Test files are excluded (they build inputs for pure functions). POSIX/BusyBox-safe,
# and fails closed: a grep error is a failure, not a pass.
set -eu
cd "$(dirname "$0")/.."

files=$(find src -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.css' \) ! -name '*.test.ts' ! -name '*.test.tsx')
[ -n "$files" ] || { echo "no source files found" >&2; exit 2; }

status=0
# shellcheck disable=SC2086
found=$(grep -niE 'mock|dummy|fake[A-Z_ ]|fixture|sampleData|Math\.random|faker' $files) || status=$?
if [ "$status" -gt 1 ]; then
  echo "grep failed (status $status)" >&2
  exit 2
fi
json=$(find src public -name '*.json')

if [ -n "$found" ] || [ -n "$json" ]; then
  echo "Invented or bundled data found in the console:" >&2
  [ -n "$found" ] && echo "$found" >&2
  [ -n "$json" ] && echo "$json" >&2
  exit 1
fi
echo "no mock, random or fixture data in $(echo "$files" | wc -l) source files"
