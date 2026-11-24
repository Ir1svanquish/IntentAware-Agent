#!/bin/zsh
# Run module C locally with a separate, persistent manual-mode database.
cd -- "$(dirname -- "$0")" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  print '请先按 README 安装 .venv 开发环境。'
  exit 1
fi
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python -m intentaware --manual --condition P --data-dir "$PWD/local-memory-data"
