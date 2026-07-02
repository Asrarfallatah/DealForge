# backend/tools/crm_tools.py

"""
Compatibility file.

Old tests may import from tools.crm_tools.
The real code is split into:
- read_tools.py
- write_tools.py
- reporting_tools.py
- approval_tools.py
"""

from tools.read_tools import *
from tools.write_tools import *
from tools.reporting_tools import *
from tools.approval_tools import *
from tools.enrichment_tools import *