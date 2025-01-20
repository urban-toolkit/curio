import os
from dotenv import load_dotenv


basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))
load_dotenv(os.path.join(basedir, '.flaskenv'))

class Config:
    LOG_TO_STDOUT = os.environ.get('LOG_TO_STDOUT')

    # Flask-Caching related configs
    CACHE_TYPE = "FileSystemCache"
    CACHE_DEFAULT_TIMEOUT = 30000
    CACHE_IGNORE_ERRORS=True
    CACHE_DIR="./flask_cache"

    os.environ.setdefault('FLASK_APP', 'server.py')