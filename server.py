#!/usr/bin/python
from flask import request, Flask, render_template
from werkzeug.utils import secure_filename
import requests
import yaml
import os
import yagmail
from yagmail import validate
from yagmail.error import YagInvalidEmailAddress
import datetime
import logging

import config
if config.decoder_enabled:
    from decoder import DecoderQueue
else:
    print("Decoder disabled; using fake decoder")
    from fake_decoder import DecoderQueue

# config
NUM_DECODER_PROCESSES = 1
WAV_UPLOAD_FOLDER = 'wav_uploads/'
ALLOWED_EXTENSIONS = ("wav", "wave")
MAX_WAVFILE_DURATION_S = 20
MAX_WAVFILE_SIZE_B = 10e6 # set in nginx config for production server
PACKET_API_ROUTE = "http://localhost:3000/equisat/receive/raw"

app = Flask(__name__)
decoder = DecoderQueue()

# limit upload file size
app.logger.setLevel(logging.DEBUG)

# setup email
if hasattr(config, "gmail_user") and hasattr(config, "gmail_user"):
    yag = yagmail.SMTP(config.gmail_user, config.gmail_pass)
else:
    app.logger.warning("incomplete config.py; will not send emails")
    yag = None

@app.route('/')
def root():
    return render_template('index.html', max_wavfile_size_b=MAX_WAVFILE_SIZE_B, max_wavfile_duration_s=MAX_WAVFILE_DURATION_S)

@app.errorhandler(413)
def too_large_request(e):
    return render_template('error_page.html', error=e, msg="Your uploaded file was too large"), 413

@app.errorhandler(404)
def page_not_found(e):
    return render_template('error_page.html', error=e, msg=""), 404

@app.route('/upload', methods=["POST"])
def upload_form():
    # initial validation
    try:
        validate.validate_email_with_regex(request.form["email"])
    except YagInvalidEmailAddress:
        title = "Invalid email address"
        message = "We send you the results of the decoding by email, so we'll need a valid email address. We don't store your address after sending you the results."
        return render_template("decode_submit.html", title=title, message=message)

    try:
        # parse in rx_time as local time
        rx_time = datetime.datetime.strptime(request.form["rx_time_date"] + " " + request.form["rx_time_time"], "%Y-%m-%d %H:%M")
    except ValueError:
        title = "Invalid received time provided or left out"
        message = "It appears that you didn't enter the time you received the data correctly. Please make sure you correctly entered the date, time, and timezone in which you received your data."
        return render_template("decode_submit.html", title=title, message=message)

    # convert RX time fields into datetime
    # then convert to UTC time using entered timezone
    rx_time_timezone = request.form["rx_time_timezone"]
    tz_hours = int(rx_time_timezone[:3])
    tz_minutes = int(60*(float(rx_time_timezone[4:])/100.0))
    rx_time = rx_time - datetime.timedelta(hours=tz_hours, minutes=tz_minutes)

    if rx_time > datetime.datetime.utcnow():
        title = "Your received time was in the future"
        message = "It appears that you entered a time in the future for the time you received this transmission. Check that you chose the correct time zone and entered the date and time correctly."
        return render_template("decode_submit.html", title=title, message=message)


    # wavfile validation
    wavfilename = save_wavfile()
    if wavfilename is None:
        title = "No WAV file provided or wrong file type"
        message = "Please make sure to upload a WAV file (.wav or .wave) according to the specified requirements"
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
            app.logger.info("[%s] submitting decode request; rx_time: %s, submit_to_db: %s, post_publicly: %s, wavfilename: %s",
                            request.form["station_name"], rx_time, request.form.has_key("submit_to_db"), request.form.has_key("post_publicly"), wavfilename)

            decoder.submit(wavfilename, on_complete_decoding, args={
                "email": request.form["email"],
                "rx_time": rx_time,
                "station_name": request.form["station_name"],
                "submit_to_db": request.form.has_key("submit_to_db") or request.form.has_key("post_publicly"), # submit to db is prereq
                "post_publicly": request.form.has_key("post_publicly")
            })
            title = "WAV file submitted successfully!"
            message = "Your file is queued to be decoded. You should be receiving an email shortly (even if there were no results). "
            if request.form.has_key("submit_to_db"):
                message += "Thank you so much for your help in providing us data on EQUiSat!"
            else:
                message += "Thank you for your interest in EQUiSat!"

    return render_template("decode_submit.html", title=title, message=message)

def save_wavfile():
    # check if the post request has the file part
    if 'wavfile' not in request.files:
        app.logger.warning("Invalid form POST for file upload")
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
    app.logger.debug("[%s] removing used wavfile %s", args["station_name"], wavfilename)
    os.remove(wavfilename)

    # publish packet if user desires
    num_published = publish_packets(packets, args)

    # send email to person with decoded packet info
    send_decode_results(wavfilename, packets, args, num_published)

def publish_packets(packets, args):
    num_published = 0
    for packet in packets["corrected_packets"]:
        if len(packet["decode_errs"]) == 0:
            published = submit_packet(packet["raw"], packet["corrected"], args["post_publicly"], args["rx_time"], args["station_name"], config.api_key)
            if published:
                num_published += 1
        else:
            app.logger.debug("[%s] did not submit packet to DB due to decode errors: %s", args["station_name"], packet["decode_errs"])
    return num_published

def submit_packet(raw, corrected, post_publicly, rx_time, station_name, api_key):
    epoch = datetime.datetime(1970, 1, 1)
    rx_time_posix = (rx_time - epoch).total_seconds()*1000 # ms since 1970

    jsn = {
        "raw": raw,
        "corrected": corrected,
        "station_name": station_name,
        "post_publicly": post_publicly,
        "source": "decoder.brownspace.org",
        "rx_time": rx_time_posix,
        "secret": api_key,
    }

    try:
        r = requests.post(PACKET_API_ROUTE, json=jsn)
        if r.status_code == requests.codes.ok or r.status_code == 201:
            app.logger.info("[%s] submitted %spacket successfully" %
                            (station_name, "duplicate " if r.status_code == 201 else ""))
            del jsn["secret"] # remove hidden info
            app.logger.debug("Full POST request:\n%s", jsn)
            return True
        else:
            app.logger.warning("[%s] couldn't submit packet (%d): %s" % (station_name, r.status_code, r.text))
            return False
    except Exception as ex:
        app.logger.error("[%s] couldn't submit packet", station_name)
        app.logger.exception(ex)
        return False

def send_decode_results(wavfilename, packets, args, num_published):
    subject = "EQUiSat Decoder Results for %s" % args["station_name"]

    raw_packets = packets["raw_packets"]
    raw_packets_summary = "Raw packets (%d detected):\n" % len(raw_packets)
    for i in range(len(raw_packets)):
        raw_packets_summary += "packet #%d hex:\n\t%s\n" % (i+1, raw_packets[i])

    corrected_packets = packets["corrected_packets"]
    corrected_packets_summary = "Valid error-corrected packets (%d detected):\n" % len(corrected_packets)
    for i in range(len(corrected_packets)):
        parsed_yaml = yaml.dump(corrected_packets[i]["parsed"], default_flow_style=False)
        decode_errs_s = "none" if len(corrected_packets[i]["decode_errs"]) == 0 else ", ".join(corrected_packets[i]["decode_errs"])
        corrected_packets_summary += "packet #%d:\nhex:\n\t%s\nerrors in decoding: %s\ndecoded data:\n %s\n\n" % \
                                     (i+1, corrected_packets[i]["corrected"], decode_errs_s, parsed_yaml)
    if len(corrected_packets) > 0:
        corrected_packets_summary += "To learn more about the decoded data, see <a href=\"https://docs.google.com/spreadsheets/d/e/2PACX-1vSCpr4KPwXkXyEMv6oPps-kVsNsd_Ell5whlvj-0T_5N9dIH5jvBTHCl6eZ_xVBugYEiL5CNR-p45G7/pubhtml?gid=589366724\">this table</a>"

    if num_published > 0:
        if args["post_publicly"]:
            extra_msg = "%d of your packets were added to our database and should have been posted to <a href=\"https://twitter.com/equisat_bot\">Twitter</a>!\n\n" % num_published
        else:
            extra_msg = "%d of your packets were added to our database!\n\n" % num_published
    elif args["submit_to_db"]:
        extra_msg = "Your packets unfortunately had too many errors to be added to our database or posted publicly."

    cleaned_wavfilename = os.path.basename(wavfilename)

    contents = """Hello %s,
    
Here are your results from the <a href="http://decoder.brownspace.org">EQUiSat Decoder</a> for your file '%s':

%s

%s

%sThank you so much for your interest in EQUiSat!

Best,
The Brown Space Engineering Team

Our website: <a href="brownspace.org">brownspace.org</a>
EQUiSat homepage: <a href="equisat.brownspace.org">equisat.brownspace.org</a>
Twitter: <a href="twitter.com/BrownCubeSat">twitter.com/BrownCubeSat</a>
Facebook: <a href="facebook.com/browncubesat">facebook.com/BrownCubeSat</a>
GitHub: <a href="github.com/brownspaceengineering">github.com/BrownSpaceEngineering</a>
Email us: <a href="mailto:bse@brown.edu">bse@brown.edu</a>

""" % (args["station_name"], cleaned_wavfilename, raw_packets_summary, corrected_packets_summary, extra_msg)

    # print(contents)

    if yag is not None:
        try:
            yag.send(to=args["email"], subject=subject, contents=contents)
            app.logger.debug("[%s] sent email with info on packets (raw: %d, corrected: %d)",
                             args["station_name"], len(raw_packets), len(corrected_packets))
        except Exception as ex:
            app.logger.error("[%s] email failed to send", args["station_name"])
            app.logger.exception(ex)

def start_decoder(num_procs=NUM_DECODER_PROCESSES):
    decoder.start(num_procs)

if __name__ == "__main__":
    start_decoder()
    app.run(debug=True)
    # see run.py for production runner