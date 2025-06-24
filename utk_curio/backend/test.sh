trap "kill 0" SIGINT;
python -m pytest tests/ -v
