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
import urllib
from bs4 import BeautifulSoup

import config
if config.decoder_enabled:
    from decoder import DecoderQueue
else:
    print("Decoder disabled; using fake decoder")
    from fake_decoder import DecoderQueue

# config
NUM_DECODER_PROCESSES = 1
AUDIO_UPLOAD_FOLDER = 'wav_uploads/'
MAX_AUDIOFILE_DURATION_S = 140
MAX_AUDIOFILE_SIZE_B = 20e6 # set in nginx config for production server
PACKET_API_ROUTE = "http://api.brownspace.org/equisat/receive/raw"

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
    return render_template('index.html', max_audiofile_size_b=MAX_AUDIOFILE_SIZE_B, max_audiofile_duration_s=MAX_AUDIOFILE_DURATION_S)

@app.errorhandler(413)
def too_large_request(e):
    return render_template('error_page.html', error=e, msg="Your uploaded file was too large"), 413

@app.errorhandler(404)
def page_not_found(e):
    return render_template('error_page.html', error=e, msg=""), 404

## File decoding

@app.route('/decode_file', methods=["POST"])
def decode_file():
    # initial validation
    valid, ret = validate_email(request.form["email"])
    if not valid:
        return ret

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

    # audio file validation
    filename = save_audiofile()
    if filename is None:
        title = "No audio file provided"
        message = "Please make sure to upload an audio file using the form."
    else:
        # convert audio file to WAV and get metadata for filtering
        wavfilename, sample_rate, duration, _ = decoder.convert_audiofile(filename)
        # remove original file now, unless it was originally a wav
        if filename != wavfilename:
            os.remove(filename)

        if wavfilename is None:
            title = "Audio file conversion failed"
            message = "We need to convert your audio file to a 16-bit PCM WAV file, but the conversion failed. " \
                      "Make sure your audio file format is supported by libsndfile (see link on main page)." \
                      "You can also try converting the file yourself using a program such as Audacity or ffmpeg."
        elif duration > MAX_AUDIOFILE_DURATION_S:
            title = "Audio file too long"
            message = "Your submitted file was too long (maximum duration is %ds, yours was %ds). " \
                      "You can try shortening the audio duration using a program such as Audacity." % (MAX_AUDIOFILE_DURATION_S, duration)
            # remove the unused file
            os.remove(wavfilename)
        else:
            app.logger.info("[%s] submitting FILE decode request; rx_time: %s, submit_to_db: %s, post_publicly: %s, wavfilename: %s",
                            request.form["station_name"], rx_time, request.form.has_key("submit_to_db"), request.form.has_key("post_publicly"), wavfilename)

            decoder.submit(wavfilename, on_complete_decoding, args={
                "email": request.form["email"],
                "rx_time": rx_time,
                "station_name": request.form["station_name"],
                "submit_to_db": request.form.has_key("submit_to_db") or request.form.has_key("post_publicly"), # submit to db is prereq
                "post_publicly": request.form.has_key("post_publicly")
            })
            title = "Audio file submitted successfully!"
            message = "Your file is queued to be decoded. You should be receiving an email shortly (even if there were no results). "
            if request.form.has_key("submit_to_db"):
                message += "Thank you so much for your help in providing us data on EQUiSat!"
            else:
                message += "Thank you for your interest in EQUiSat!"

    return render_template("decode_submit.html", title=title, message=message)

def save_audiofile():
    # check if the post request has the file part
    if 'audiofile' not in request.files:
        app.logger.warning("Invalid form POST for file upload")
        return None

    audiofile = request.files['audiofile']
    # if user does not select file, browser also
    # submit an empty part without filename
    if audiofile.filename == '':
        return None
    if audiofile:
        # clean filename for security
        filename = secure_filename(audiofile.filename)
        filepath = os.path.join(AUDIO_UPLOAD_FOLDER, filename)
        audiofile.save(filepath)
        return filepath

## SatNOGS decoding

@app.route('/decode_satnogs', methods=["POST"])
def decode_satnogs():
    # initial validation
    valid, ret = validate_email(request.form["email"])
    if not valid:
        return ret

    try:
        int(request.form["obs_id"])
    except ValueError:
        title = "Invalid observation ID"
        message = "Your observation ID was not a valid integer number"
        return render_template("decode_submit.html", title=title, message=message)

    if request.form["start_s"] == "":
        start_s = 0
    else:
        try:
            start_s = int(request.form["start_s"])
            if start_s < 0:
                title = "Negative start time"
                message = "Your start time must be positive; leave the field blank to use the start of the file"
                return render_template("decode_submit.html", title=title, message=message)

        except ValueError:
            title = "Invalid start time"
            message = "Your start time was not a valid integer number"
            return render_template("decode_submit.html", title=title, message=message)

    if request.form["stop_s"] == "":
        stop_s = None
    else:
        try:
            stop_s = int(request.form["stop_s"])
            if stop_s < 0:
                title = "Negative stop time"
                message = "Your stop time must be positive; leave the field blank to use the end of the file"
                return render_template("decode_submit.html", title=title, message=message)
        except ValueError:
            title = "Invalid start time"
            message = "Your start time was not a valid integer number"
            return render_template("decode_submit.html", title=title, message=message)

    if start_s != 0 and stop_s is not None and start_s >= stop_s:
        title = "Start time wasn't before stop time"
        message = "Your start time needs to be less than your stop time"
        return render_template("decode_submit.html", title=title, message=message)

    # try to get observation data
    logging.info("[obs %s] pulling data from SatNOGS" % request.form["obs_id"])
    obs_data = scrape_satnogs_metadata(request.form["obs_id"])
    logging.debug("[obs %s] got SatNOGS data: %s" % (request.form["obs_id"], obs_data))

    # validate the observation properties
    if obs_data is None:
        title = "Observation not found or incomplete"
        message = "We could not find an observation under the ID you provided, or the page for observation was incomplete. " \
                  "Make sure the page for that observation is available on SatNOGS "
        return render_template("decode_submit.html", title=title, message=message)
    elif obs_data["status"] == "pending":
        title = "Observation is in the future"
        message = "The observation had status 'future' so there is no data available to decode"
        return render_template("decode_submit.html", title=title, message=message)
    elif obs_data["audio_url"] is None:
        title = "No audio found for observation"
        message = "We couldn't find an audio file listed under this observation. " \
                  "It's possible that the observation failed and the station did not upload audio."
        return render_template("decode_submit.html", title=title, message=message)

    rx_time = obs_data["start_time"] + datetime.timedelta(seconds=start_s)

    # get file
    filename = AUDIO_UPLOAD_FOLDER + os.path.basename(obs_data["audio_url"])
    logging.info("[obs %s] retrieving audio file from %s" % (request.form["obs_id"], obs_data["audio_url"]))
    urllib.urlretrieve(obs_data["audio_url"], filename)

    # convert audio file to WAV and get metadata for filtering
    wavfilename, sample_rate, duration, _ = decoder.convert_audiofile(filename)
    os.remove(filename) # remove original file

    if wavfilename is None:
        title = "Audio file conversion failed"
        message = "We need to convert your audio file to a 16-bit PCM WAV file, but the conversion failed. " \
                  "Make sure your audio file format is supported by libsndfile (see link on main page)." \
                  "You can also try converting the file yourself using a program such as Audacity or ffmpeg."
        return render_template("decode_submit.html", title=title, message=message)

    # slice audio file to desired duration
    success, duration = decoder.slice_audiofile(wavfilename, start_s, stop_s, sample_rate)

    if not success:
        title = "Audio file slicing failed"
        message = "We were unable to shorten the audio file according to the start and end times you specified. " \
                  "You can try removing these values or not using negative values."
        # remove the unused file
        os.remove(wavfilename)

    elif duration > MAX_AUDIOFILE_DURATION_S:
        title = "Specified duration too long"
        message = "The duration you specified with your start and end times was too long. " \
                  "You can try specifying a shorter or more specific duration (i.e. try not leaving the fields blank)."
        # remove the unused file
        os.remove(wavfilename)

    else:
        app.logger.info("Submitting SATNOGS decode request; obs_id: %s, time interval: [%ss, %ss], rx_time: %s, submit_to_db: %s, post_publicly: %s, wavfilename: %s",
                        request.form["obs_id"], start_s, stop_s, rx_time, request.form.has_key("submit_to_db"), request.form.has_key("post_publicly"), wavfilename)

        decoder.submit(wavfilename, on_complete_decoding, args={
            "email": request.form["email"],
            "rx_time": rx_time,
            "station_name": obs_data["station_name"],
            "submit_to_db": request.form.has_key("submit_to_db") or request.form.has_key("post_publicly"), # submit to db is prereq
            "post_publicly": request.form.has_key("post_publicly")
        })
        title = "SatNOGS observation submitted successfully!"
        message = "The observation is queued to be decoded. You should be receiving an email shortly (even if there were no results). "
        if request.form.has_key("submit_to_db"):
            message += "Thank you so much for your help in providing us data on EQUiSat!"
        else:
            message += "Thank you for your interest in EQUiSat!"

    return render_template("decode_submit.html", title=title, message=message)

def scrape_satnogs_metadata(obs_id):
    page = requests.get("https://network.satnogs.org/observations/%s" % obs_id)

    if page.status_code == 404:
        # no observation found
        return None
    else:
        soup = BeautifulSoup(page.text, 'html.parser')

        try:
            # get side column
            side_col_rows = soup.body.find_all(attrs={"class":"front-line"})

            # extract status
            # <span class ="label label-xs label-good" aria-hidden="true" data-toggle="tooltip" data-placement="right" title=""
            # data-original-title="Vetted good on 2019-01-07 00:16:28 by Brown Space Engineering">Good</span>
            status_span = side_col_rows[3].findChildren()[2] # findChildren returns flat list of all nested children
            status = status_span.text.lower()

            # extract station name
            # <a href="/stations/291/">
            #   291 - COSPAR 8049
            # </a>
            full_station_name = side_col_rows[1].a.text
            dash_i = full_station_name.index("-")
            station_name = full_station_name[dash_i+1:].strip()

            # extract and convert observation start time
            start_time_span = side_col_rows[7].findChildren()[2]
            start_time_str = start_time_span.contents[1].text + "T" + start_time_span.contents[3].text
            start_time = datetime.datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M:%S")

            # extract URL of audio file
            # <a href="/media/data_obs/399165/satnogs_399165_2019-01-07T00-01-01.ogg" target="_blank" download="">
            #     <button type="button" class="btn btn-default btn-xs" >
            #         <span class ="glyphicon glyphicon-download"></span>
            #         Audio
            #     </button>
            # </a>
            if len(side_col_rows) < 15:
                audio_url = None
            else:
                first_a = side_col_rows[14].a
                # check if the icon exists and if it's the audio one
                if first_a is None or first_a["href"].find(".ogg") == -1:
                    audio_url = None
                else:
                    audio_url = "https://network.satnogs.org" + first_a["href"]

            return {
                "status": str(status),
                "station_name": str(station_name),
                "start_time": start_time,
                "audio_url": str(audio_url)
            }

        except IndexError or ValueError as ex:
            logging.error("Error while parsing SatNOGS station page for observation %s", obs_id)
            logging.exception(ex)
            return None

## Post-decoding helpers

def validate_email(email):
    try:
        validate.validate_email_with_regex(email)
        return True, None
    except YagInvalidEmailAddress:
        title = "Invalid email address"
        message = "We send you the results of the decoding by email, so we'll need a valid email address. We don't store your address after sending you the results."
        return False, render_template("decode_submit.html", title=title, message=message)

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
    if args["submit_to_db"]:
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
        corrected_packets_summary += "To learn more about the decoded data, see this table: <a href=\"https://goo.gl/Kj9RkY\">https://goo.gl/Kj9RkY</a>"

    extra_msg = ""
    if len(raw_packets) == 0 or len(corrected_packets) == 0:
        extra_msg = "Sorry nothing was found! We're still working on the decoder, so keep trying and check back later!\n\n"
    if num_published > 0:
        if args["post_publicly"]:
            extra_msg = "%d of your packets were added to our database and should have been posted to <a href=\"https://twitter.com/equisat_bot\">Twitter</a>!\n\n" % num_published
        else:
            extra_msg = "%d of your packets were added to our database!\n\n" % num_published
    elif args["submit_to_db"]:
        extra_msg = "Your packets unfortunately had too many errors to be added to our database or posted publicly.\n\n"

    cleaned_wavfilename = os.path.basename(wavfilename)

    contents = """Hello %s,
    
Here are your results from the EQUiSat Decoder <a href="http://decoder.brownspace.org">decoder.brownspace.org</a>, for your converted file '%s':

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