#!/usr/bin/env bash
# Полная проверка: код готов, когда она зелёная (ADR-0007).
set -euo pipefail
here="$(dirname "$0")"
"$here/lint.sh"
"$here/typecheck.sh"
"$here/test.sh"
