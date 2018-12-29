#!/usr/bin/python
from flask import request, Flask
from decoder import DecoderQueue
app = Flask(__name__)

NUM_DECODER_PROCESSES = 1
decoder = DecoderQueue()

@app.route('/')
def root():
    return app.send_static_file('index.html')

@app.route('/upload', methods=["POST", "GET"])
def upload_form():
    # TODO: upload file

    wavfilename = "..."
    decoder.submit(wavfilename, on_complete_decoding, args={
        "email": request.form["email"],
        "rx_time": request.form["rx_time"],
        "station_name": request.form["station_name"],
        "submit_to_db": request.form["submit_to_db"],
        "post_publicly": request.form["post_publicly"]
    })

    # return done page
    return ""

def on_complete_decoding(packets, args):
    # TODO: send email to person with _decoded_ packet
    # TODO: publish packet if desired
    pass

def main():
    decoder.start(NUM_DECODER_PROCESSES)
    app.run()

if __name__ == "__main__":
    main()