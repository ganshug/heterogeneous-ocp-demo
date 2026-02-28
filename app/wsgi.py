"""
WSGI entry point for gunicorn.

Usage (in Dockerfile / CMD):
    gunicorn --bind 0.0.0.0:8080 --workers 2 --timeout 60 wsgi:application

The OCP S2I Python builder also looks for wsgi.py automatically.
"""

from app import app as application  # noqa: F401

if __name__ == "__main__":
    application.run(host="0.0.0.0", port=8080, debug=False)