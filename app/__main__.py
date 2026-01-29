from app import create_app
from app.config import config

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=config.BOT_PORT, threaded=True)
