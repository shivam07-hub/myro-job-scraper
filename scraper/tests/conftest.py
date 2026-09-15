"""Make the flat scraper modules importable from tests/.

The providers and top-level modules use flat imports (`from schema import ...`,
`import providers.zwayam`), which assume the scraper/ directory is on sys.path.
With the tests now in scraper/tests/, add the parent (scraper/) so those imports
resolve no matter where pytest is invoked from.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
