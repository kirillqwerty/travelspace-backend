import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, CURRENT_DIR)
os.chdir(CURRENT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(CURRENT_DIR, ".env"))

from a2wsgi import ASGIMiddleware
from server import app as fastapi_app

application = ASGIMiddleware(fastapi_app)