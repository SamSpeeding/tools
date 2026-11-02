#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v python3 >/dev/null 2>&1; then
  echo '找不到 Python 3，请先安装 Python 3.10 或更新版本。'
  result=1
else
  python3 collector.py sync "$@"
  result=$?
fi
if [ -t 0 ]; then
  printf '\n执行结束（退出码 %s）。按回车关闭窗口。' "$result"
  read -r _catalog_reply
fi
exit "$result"
