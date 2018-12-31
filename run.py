#!/usr/bin/env python
from gevent.pywsgi import WSGIServer
from server import app
from server import start_decoder
import logging

# start decoder worker process
start_decoder()

# setup logging
app.logger.setLevel(logging.DEBUG)

# see nginx config for port 80 proxy
http_server = WSGIServer(('', 5000), app)

try:
    app.logger.info("Started server")
    http_server.serve_forever()
except KeyboardInterrupt:
    pass