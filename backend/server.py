import os
from app import create_app

app = create_app()

@app.route('/health', methods=['GET'])
def health():
    return 'OK', 200

if __name__ == '__main__':
    app.run(
        host=os.getenv('FLASK_RUN_HOST', 'localhost'),
        port=int(os.getenv('FLASK_RUN_PORT', 5002)),
        threaded=False,
    )

