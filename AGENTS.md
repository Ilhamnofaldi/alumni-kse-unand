# Agen

Proyek website alumni KSE UNAND (Flask + SQLite).

Baca skill di `.cursor/skills/` sebelum mengubah data atau UI:

1. `alumni-kse-domain` — istilah dan sumber data
2. `alumni-privacy-pii` — apa yang boleh tampil publik
3. `alumni-csv-import` — impor CSV opsional
4. `alumni-web-flask` — cara jalan dan letak kode
5. `alumni-qa` — checklist tes

Jangan commit CSV asli, `instance/alumni.db`, atau `.env`.

Dev: `python run.py`. Produksi: `wsgi:app` lewat gunicorn/waitress, dan `python -m alumni_web.cli setup` sebagai langkah deploy (boot aplikasi sengaja tidak menyiapkan database).
