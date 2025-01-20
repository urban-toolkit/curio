import os
from app import app

if __name__ == '__main__':
    app.run(
        host=os.environ['FLASK_RUN_HOST'],
        port=os.environ['FLASK_RUN_PORT'],
        threaded=False
    )
