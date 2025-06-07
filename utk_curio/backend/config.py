import os
from dotenv import load_dotenv


basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))
load_dotenv(os.path.join(basedir, '.flaskenv'))

class Config:
    LOG_TO_STDOUT = os.environ.get('LOG_TO_STDOUT')

    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
                              'sqlite:///urban_workflow.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = True

    WTF_CSRF_ENABLED = True

    ADMINS = ['your-email@example.com']

    SANDBOX_RELATIVE_PATH = (os.environ.get('SANDBOX_RELATIVE_PATH') or
                             '../sandbox')
    FRONTEND_RELATIVE_PATH = (os.environ.get('FRONTEND_RELATIVE_PATH') or
                                '../urban-workflows')
    FRONTEND_PORT = os.environ.get('FRONTEND_PORT') or 3000
    SANDBOX_PORT = os.environ.get('SANDBOX_PORT') or 2000

