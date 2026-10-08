# SQLite hanya menerima satu penulis: pakai satu proses dengan beberapa thread.
bind = "127.0.0.1:8000"
workers = 1
threads = 4
worker_class = "gthread"
timeout = 120
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
loglevel = "info"
