run:
	rm -rf studies/*
	python3 filter.py

app:
	cd $(CURDIR) && uvicorn web.app:app --host 0.0.0.0 --port 9090 --reload
