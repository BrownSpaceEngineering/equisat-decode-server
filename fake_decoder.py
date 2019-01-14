import soundfile as sf
import logging

WAVFILE_CONV_SUBTYPE = "PCM_16"

class DecoderQueue:
    def __init__(self):
        pass

    def start(self, num):
        pass

    def stop(self):
        pass

    def submit(self, wavfilename, onfinish, args):
        onfinish(wavfilename, {
            "raw_packets": [],
            "corrected_packets": [],
        }, args)

    @staticmethod
    def get_audio_info(filename):
        data, sample_rate = sf.read(filename)
        nframes = len(data)
        duration = nframes / sample_rate
        return sample_rate, duration, nframes

    @staticmethod
    def convert_audiofile(filename, subtype=WAVFILE_CONV_SUBTYPE):
        """ Converts the given file to a .wav file with the given subtype"""
        try:
            data, sample_rate = sf.read(filename)
            doti = filename.rfind(".")
            if doti == -1:
                wavfilename = filename + ".wav"
            else:
                wavfilename = filename[:doti] + ".wav"

            sf.write(wavfilename, data, sample_rate, subtype=subtype)

            nframes = len(data)
            duration = nframes / sample_rate
            return wavfilename, sample_rate, duration, nframes

        except RuntimeError as ex:  # soundfile error
            logging.error("Error converting audio file '%s' to wav", filename)
            logging.exception(ex)
            return None, 0, 0, 0

    @staticmethod
    def slice_audiofile(filename, start_s, stop_s, sample_rate):
        """ Slices the given audio file from start_s seconds to end_s seconds
        and overwrites the file. If start_s or end_s are negative,
        they reference from the end of the file.
        Returns whether the process was successful and the new duration """
        if start_s is None:
            start_i = 0
        else:
            start_i = start_s * sample_rate

        if stop_s is None:
            stop_i = None
        else:
            stop_i = stop_s * sample_rate

        try:
            data, _ = sf.read(filename, start=start_i, stop=stop_i)
            sf.write(filename, data, sample_rate)
            duration = len(data) / sample_rate
            return True, duration

        except RuntimeError as ex:  # soundfile error
            logging.error("Error slicing audio file '%s'", filename)
            logging.exception(ex)
            return False, 0