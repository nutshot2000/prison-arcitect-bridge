#!/bin/sh
# Build pa_bridge (installed as GLU32.dll) into bin/GLU32.dll. No Windows SDK or CRT needed.
#
# Uses clang + lld-link + llvm-dlltool when they are on PATH. Otherwise it uses zig, which
# is pip-installable on Windows:  python -m pip install ziglang   (then run this from Git Bash).
set -e
cd "$(dirname "$0")"
FLAGS="-O2 -ffreestanding -fno-builtin -fno-stack-protector -mno-stack-arg-probe -Wall -Wno-unused-function"

if command -v clang >/dev/null && command -v lld-link >/dev/null && command -v llvm-dlltool >/dev/null; then
    llvm-dlltool -m i386:x86-64 -d kernel32.def -l kernel32.lib
    llvm-dlltool -m i386:x86-64 -d ws2_32.def -l ws2_32.lib
    clang --target=x86_64-pc-windows-msvc $FLAGS -c pa_bridge.c -o pa_bridge.obj
    lld-link /dll /nodefaultlib /entry:DllMain /def:glu32.def /out:bin/GLU32.dll /machine:x64 \
             /subsystem:windows pa_bridge.obj kernel32.lib ws2_32.lib
    rm -f pa_bridge.obj kernel32.lib ws2_32.lib bin/GLU32.lib bin/GLU32.exp
else
    PY=${PYTHON:-python}
    [ -x ../.venv/Scripts/python.exe ] && PY=../.venv/Scripts/python.exe
    $PY -m ziglang cc -target x86_64-windows-gnu -shared -nostdlib $FLAGS pa_bridge.c glu32.def \
        -lkernel32 -lws2_32 -Wl,--entry=DllMain -o bin/GLU32.dll
    rm -f bin/GLU32.lib bin/GLU32.pdb bin/pa_bridge.lib
fi
echo built bin/GLU32.dll
