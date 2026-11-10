#!/bin/zsh
set -e
cd -- "${0:A:h}"
if [[ -x .runtime/python/bin/python3.11 ]]; then
  .runtime/python/bin/python3.11 -m venv .venv
elif command -v python3.11 >/dev/null; then
  python3.11 -m venv .venv
else
  printf '需要 Python 3.11。请先安装后重新运行。\n'
  read -r
  exit 1
fi
.venv/bin/python -m pip install -r requirements.txt
printf '\n环境准备完成。可双击 启动.command。按回车关闭…'
read -r
