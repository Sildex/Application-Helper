"""Application Helper – Desktop App"""
import os
import sys

if getattr(sys, "frozen", False):
    import certifi
    os.environ["SSL_CERT_FILE"]      = certifi.where()
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from app.ui import run

if __name__ == "__main__":
    run()
