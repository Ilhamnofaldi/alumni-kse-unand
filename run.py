"""Server pengembangan lokal. Untuk produksi pakai wsgi.py."""

import os

from alumni_web import create_app
from alumni_web.boot import prepare

app = create_app()

if __name__ == "__main__":
    prepare(app, auto_import=True, allow_generate=True, include_root=True)
    debug = os.environ.get("FLASK_DEBUG") == "1" and os.environ.get("ALUMNI_ENV") != "production"
    # Tanpa debug, Jinja meng-cache template selama proses hidup. Di dev itu
    # menyesatkan: berkas sudah diubah tapi halaman tidak berubah.
    app.jinja_env.auto_reload = True
    app.run(host="127.0.0.1", port=5000, debug=debug)
