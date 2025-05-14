from sandbox.app import app
import os

@app.route('/health', methods=['GET'])
def health():
    return 'OK', 200

if __name__ == '__main__':
    app.run(
        host=os.getenv('FLASK_RUN_HOST', 'localhost'),
        port=int(os.getenv('FLASK_RUN_PORT', 2000)),
        threaded=False,
        debug=True
    )

