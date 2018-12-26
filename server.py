#!/usr/bin/python
from flask import request, Flask
from decoder import DecoderQueue
app = Flask(__name__)

NUM_DECODER_PROCESSES = 1
decoder = DecoderQueue()

@app.route('/')
def home():
    return "Hello"

@app.route('/upload', methods=["POST", "GET"])
def upload_form():
    # TODO: upload file

    wavfilename = "..."
    sample_rate = request.form["sample_rate"]

    decoder.submit(wavfilename, sample_rate, on_complete_decoding, args={
        "email": request.form["email"],
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