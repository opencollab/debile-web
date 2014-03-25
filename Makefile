#!/usr/bin/make -f

all: build install

dev: all lint

devel:
	./devel.sh

lint:
	flake8 debileweb

build install clean distclean:
	$(MAKE) -C less $@

.PHONY: all dev devel lint build install clean distclean
