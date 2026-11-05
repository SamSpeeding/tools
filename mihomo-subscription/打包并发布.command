#!/bin/zsh
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
cd -- "${0:A:h}" || exit 1

if ! command -v php >/dev/null || ! command -v python3 >/dev/null; then
    print '需要 PHP 8.1+ 和 Python 3，请先安装后重试。'
    task_exit=1
else
    python3 bin/deploy.py "$@"
    task_exit=$?
fi

if [[ -t 0 && -t 1 ]]; then
    read "?按回车关闭窗口…"
fi
exit "$task_exit"
