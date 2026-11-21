"""Gunicorn settings for the college server (used by deploy/systemd/asset-portal.service)."""
import multiprocessing

# Nginx talks to Gunicorn over a local socket (created by systemd).
bind = "unix:/run/asset-portal/gunicorn.sock"

# A few workers are plenty for a department; SQLite is happiest with few writers.
workers = min(4, multiprocessing.cpu_count() * 2 + 1)
threads = 2
worker_class = "gthread"
timeout = 60            # bulk uploads / exports can take a few seconds
graceful_timeout = 30
max_requests = 2000      # recycle workers now and then (guards against leaks)
max_requests_jitter = 200

accesslog = "-"          # goes to the systemd journal
# Log the visitor's IP (passed on by Nginx), not the local socket.
access_log_format = '%({x-forwarded-for}i)s "%(r)s" %(s)s %(b)s %(L)ss "%(a)s"'
errorlog = "-"
loglevel = "info"
forwarded_allow_ips = "127.0.0.1"
