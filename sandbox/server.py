from app import app
import os


if __name__ == '__main__':
    app.run(
        host=os.getenv('FLASK_RUN_HOST', 'localhost'),
        port=int(os.getenv('FLASK_RUN_PORT', 2000)),
        threaded=False,
    )
