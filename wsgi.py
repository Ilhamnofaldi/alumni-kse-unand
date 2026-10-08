"""Entrypoint produksi.

Linux : gunicorn -c gunicorn.conf.py wsgi:app
Windows: waitress-serve --listen=127.0.0.1:8000 --threads=4 wsgi:app

Siapkan database dulu (sekali, bukan saat boot):
    python -m alumni_web.cli setup
"""

from werkzeug.middleware.proxy_fix import ProxyFix

from alumni_web import create_app

app = create_app()
# Satu reverse proxy di depan (Nginx/Caddy). Tanpa ini remote_addr selalu
# 127.0.0.1 dan pembatas laju jadi satu bucket global.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
