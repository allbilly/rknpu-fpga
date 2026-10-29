#!/bin/sh
exec /usr/bin/c++ "$@" -O3 -flto=1 -flto-partition=one
