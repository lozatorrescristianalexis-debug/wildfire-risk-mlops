PYTHON ?= python

.PHONY: data data-demo train run test

data:
	$(PYTHON) -m src.wildfire.cli data

data-demo:
	$(PYTHON) -m src.wildfire.cli data-demo

train:
	$(PYTHON) -m src.wildfire.cli train

run:
	$(PYTHON) -m src.wildfire.cli run

test:
	$(PYTHON) -m pytest
