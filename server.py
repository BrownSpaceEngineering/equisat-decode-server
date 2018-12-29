#!/usr/bin/python
from flask import request, Flask, render_template
from werkzeug.utils import secure_filename
from decoder import DecoderQueue
import os

# config
NUM_DECODER_PROCESSES = 1
WAV_UPLOAD_FOLDER = 'wav_uploads/'
ALLOWED_EXTENSIONS = ("wav", "wave")
MAX_WAVFILE_DURATION_S = 60
MAX_WAVFILE_SIZE_B = 20e6 # 20 MB

app = Flask(__name__)
decoder = DecoderQueue()
# limit upload file size
app.config['MAX_CONTENT_LENGTH'] = (1.1*MAX_WAVFILE_SIZE_B) * 1024 * 1024

@app.route('/')
def root():
    return render_template('index.html')

@app.route('/upload', methods=["POST", "GET"])
def upload_form():
    wavfilename = save_wavfile()
    if wavfilename is None:
        title = "No WAV file provided or too large"
        message = "Please make sure to upload a WAV file (.wav or .wave) smaller than %d MB for the server to decode" % MAX_WAVFILE_SIZE_B

    else:
        # get metadata for filtering
        sample_rate, duration, _ = decoder.get_wav_info(wavfilename)

        if duration > MAX_WAVFILE_DURATION_S:
            title = "WAV file too long"
            message = "Your submitted file was too long (maximum duration is %ds, yours was %ds). " \
                      "Try shortening the audio duration using a program such as Audacity." % (MAX_WAVFILE_DURATION_S, duration)
            # remove the unused file
            os.remove(wavfilename)
        else:
            decoder.submit(wavfilename, on_complete_decoding, args={
                "email": request.form["email"],
                "rx_time": request.form["rx_time"],
                "station_name": request.form["station_name"],
                "submit_to_db": request.form.has_key("submit_to_db"),
                "post_publicly": request.form.has_key("post_publicly")
            })
            title = "WAV file submitted successfully!"
            message = "Your file is queued to be decoded. You should be receiving an email shortly with any results. "
            if request.form.has_key("submit_to_db"):
                message += "Thank you so much for your help in providing us data on EQUiSat!"
            else:
                message += "Thank you for your interest in EQUiSat!"

    # return done page
    return render_template("decode_submit.html", title=title, message=message)

def save_wavfile():
    # check if the post request has the file part
    if 'wavfile' not in request.files:
        print("invalid form POST for file upload")
        return None

    wavfile = request.files['wavfile']
    # if user does not select file, browser also
    # submit an empty part without filename
    if wavfile.filename == '':
        return None
    if wavfile and allowed_file(wavfile.filename):
        # clean filename for security
        filename = secure_filename(wavfile.filename)
        filepath = os.path.join(WAV_UPLOAD_FOLDER, filename)
        wavfile.save(filepath)
        return filepath

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def on_complete_decoding(wavfilename, packets, args):
    # remove wavfile because we're done with it
    os.remove(wavfilename)

    # TODO: send email to person with _decoded_ packet
    # TODO: publish packet if desired
    print("finished decoding")
    pass

def main():
    decoder.start(NUM_DECODER_PROCESSES)
    app.run()

if __name__ == "__main__":
    main()