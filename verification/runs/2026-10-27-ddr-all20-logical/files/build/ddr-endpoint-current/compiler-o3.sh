#!/bin/sh
# Same Verilator-generated C++ and assertions; optimize compilation only.
exec /usr/bin/c++ "$@" -O3
