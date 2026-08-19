import os
import tempfile

# Executed at collection time, before any test module imports simulation.main
# (which constructs the module-level provider/engine/recorder). Redirecting
# run output here keeps the Run Recorder's real behaviour under test while
# never writing into the repository's simulation_output/ directory.
os.environ.setdefault("SIMULATION_RUN_OUTPUT_DIR", os.path.join(tempfile.gettempdir(), "st_simul_test_runs"))
