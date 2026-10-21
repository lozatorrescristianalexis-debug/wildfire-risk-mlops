PYTHON ?= python

.PHONY: data data-peru data-demo train train-peru run test

data:
	$(PYTHON) -m src.wildfire.cli data

data-peru:
	$(PYTHON) -m src.wildfire.cli data --region peru

data-demo:
	$(PYTHON) -m src.wildfire.cli data-demo

train:
	$(PYTHON) -m src.wildfire.cli train

train-peru:
	$(PYTHON) -m src.wildfire.cli train --region peru --trials 5

run:
	$(PYTHON) -m src.wildfire.cli run

test:
	$(PYTHON) -m pytest

.PHONY: observations observations-refresh observations-watch
observations:
	$(PYTHON) -m src.wildfire.observations build-local

observations-refresh:
	$(PYTHON) -m src.wildfire.observations refresh --days 14

observations-watch:
	$(PYTHON) -m src.wildfire.observations watch --days 14
