LESS_SCRIPTS = debile.css

LESSC = lessc
LESSCFLAGS = -x

STATIC = ../static
STATIC_CSS = $(STATIC)/css

.SUFFIXES:
.SUFFIXES: .less .css


all: build install


build: $(LESS_SCRIPTS)


install:
	mv debile.css $(STATIC_CSS)/debile.css


.less.css:
	$(LESSC) $(LESSCFLAGS) $< > $@


.PHONY: build
