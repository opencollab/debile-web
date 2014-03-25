#!/usr/bin/make -f

LESS_SCRIPTS = debile.css

LESSC = lessc
LESSCFLAGS = -x

STATIC_CSS = ../static/css

all: build install

build: $(LESS_SCRIPTS)

install: $(LESS_SCRIPTS)
	cp $(LESS_SCRIPTS) $(STATIC_CSS)/

clean:
	rm -f $(LESS_SCRIPTS)
	rm -f $(patsubst %.css,%.d,$(LESS_SCRIPTS))

distclean: clean
	rm -f $(patsubst %,$(STATIC_CSS)/%,$(LESS_SCRIPTS))

%.css: %.less
	$(LESSC) $(LESSCFLAGS) $< $@
	$(LESSC) --depends $< $@ > $*.d

-include $(patsubst %.css,%.d,$(LESS_SCRIPTS))

.PHONY: all build install clean distclean

