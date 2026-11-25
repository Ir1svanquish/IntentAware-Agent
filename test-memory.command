#!/bin/zsh
# Run the complete suite on the local machine and retain its output.
set -o pipefail
cd -- "$(dirname -- "$0")" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  print '请先按 README 安装 .venv 开发环境。'
  exit 1
fi
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
.venv/bin/python -m pytest -q "$@" 2>&1 | tee local-memory-test.log
exit $?
