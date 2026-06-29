import os
import sys

# put the benchmark package dir on the path so tests can import the eval modules as siblings.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
