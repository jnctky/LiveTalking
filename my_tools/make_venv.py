"""在项目根创建虚拟环境（绕开 `python -m venv` 在本机会话里的静默失败）。

原因：本机 WorkBuddy 会话中 `python -m venv <dir>` 退出码 0 但不创建任何文件；
直接调用 venv.EnvBuilder 则正常。此脚本用 EnvBuilder 建环境并带 pip。

用法:
    <系统python> my_tools/make_venv.py .venv [--no-pip]

示例:
    "C:/Users/pc/AppData/Local/Programs/Python/Python312/python.exe" my_tools/make_venv.py .venv
"""
import os
import sys
import traceback

target = ".venv"
with_pip = True
for a in sys.argv[1:]:
    if a == "--no-pip":
        with_pip = False
    else:
        target = a

log = open("make_venv.log", "w", encoding="utf-8")


def w(*a):
    print(*a, file=log, flush=True)


try:
    import venv
    w("python:", sys.executable, sys.version.split()[0])
    w("target:", os.path.abspath(target), "with_pip:", with_pip)
    venv.EnvBuilder(
        system_site_packages=False,
        clear=False,
        symlinks=False,
        upgrade=False,
        with_pip=with_pip,
    ).create(target)
    ok = os.path.isfile(os.path.join(target, "Scripts", "python.exe"))
    w("python.exe 存在:", ok)
    w("RESULT:", "OK" if ok else "FAILED")
except Exception:
    w("RESULT: FAILED")
    w(traceback.format_exc())
finally:
    log.close()
