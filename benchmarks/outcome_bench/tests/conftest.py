import os
import sys

# put the benchmark package dir on the path so tests import the bench modules
# as siblings (the governor_compare convention).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
