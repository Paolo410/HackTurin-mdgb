import os
import sys

# "import comms" works whatever directory pytest is started from
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
