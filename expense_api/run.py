from app import app

# Development run helper; for production use a WSGI/ASGI server.
if __name__ == "__main__":
    app.run()
