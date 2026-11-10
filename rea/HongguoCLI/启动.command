#!/bin/zsh
cd -- "${0:A:h}"
if [[ -x .venv/bin/python ]]; then
  .venv/bin/python hongguo.py "$@"
else
  printf 'Python 环境缺失，请先双击 安装依赖.command。\n'
fi
printf '\n按回车关闭窗口…'
read -r
