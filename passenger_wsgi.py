import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from a2wsgi import ASGIMiddleware
from server import app

application = ASGIMiddleware(app)