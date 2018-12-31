import wave

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
    def get_wav_info(wavfilename):
        # copied directly from decoder
        wf = wave.open(wavfilename)
        sample_rate = wf.getframerate()
        nframes = wf.getnframes()
        duration = nframes / sample_rate
        return sample_rate, duration, nframes