run:
	@PYTHONPATH=src python3 -m hybrid_agent.cli --version

solve:
	@PYTHONPATH=src python3 -m hybrid_agent.cli solve --prompt "$(P)" $(F)

test:
	@PYTHONPATH=src python3 -m unittest discover -s tests
