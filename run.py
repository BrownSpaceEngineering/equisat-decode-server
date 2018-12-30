from gevent.pywsgi import WSGIServer
from server import app
from server import start_decoder, NUM_DECODER_PROCESSES

# start decoder worker process
start_decoder(NUM_DECODER_PROCESSES)
# see nginx config for port 80 proxy
http_server = WSGIServer(('', 5000), app)

try:
    print("Started server")
    http_server.serve_forever()
except KeyboardInterrupt:
    pass