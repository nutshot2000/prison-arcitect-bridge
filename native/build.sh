#!/bin/sh
# Cross-compile pa_bridge (installed as GLU32.dll) with clang + lld-link. No Windows SDK needed.
set -e
cd "$(dirname "$0")"
llvm-dlltool -m i386:x86-64 -d kernel32.def -l kernel32.lib
llvm-dlltool -m i386:x86-64 -d ws2_32.def -l ws2_32.lib
clang --target=x86_64-pc-windows-msvc -O2 -ffreestanding -fno-builtin -fno-stack-protector \
      -mno-stack-arg-probe -Wall -Wno-unused-function -c pa_bridge.c -o pa_bridge.obj
lld-link /dll /nodefaultlib /entry:DllMain /def:glu32.def /out:GLU32.dll /machine:x64 \
         /subsystem:windows pa_bridge.obj kernel32.lib ws2_32.lib
rm -f pa_bridge.obj kernel32.lib ws2_32.lib GLU32.lib GLU32.exp
echo built GLU32.dll
