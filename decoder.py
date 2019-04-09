import multiprocessing
import Queue # for Queue.Empty
from equisat_fm_demod import equisat_fm_demod
from packetparse import packetparse
import binascii
import pmt
import soundfile as sf
import sys
import time
import logging

QUEUE_EMPTY_POLL_PERIOD = 2
FLOWGRAPH_POLL_PERIOD_S = 2
WAVFILE_CONV_SUBTYPE = "PCM_16"

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class DecoderQueue:
    def __init__(self, in_logger=None):
        self.queue = multiprocessing.Queue()
        self.procs = []
        self.stopping = multiprocessing.Value("b", False)
        if in_logger:
            global logger
            logger = in_logger

    def start(self, num):
        """ Spawns a new set of num processes which reads requests off the decode queue and performs them """
        for i in range(num):
            proc = multiprocessing.Process(target=self.decode_worker, args=(self.queue, self.stopping))
            proc.start()
            self.procs.append(proc)

    def stop(self):
        self.stopping.value = True

    def submit(self, wavfilename, onfinish, args):
        """ Submits an FM decode job (wavfilename) to the decoder queue.
        The onfinish callback receives wavfilename, a dict containing raw_packets and corrected_packets lists,
        the passed in args, and any error message (or None otherwise) """
        self.queue.put_nowait({
            "wavfilename": str(wavfilename),
            "onfinish": onfinish,
            "args": args
        })

    @staticmethod
    def get_audio_info(filename):
        data, sample_rate = sf.read(filename)
        nframes = len(data)
        duration = nframes  / sample_rate
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

        except RuntimeError as ex: # soundfile error
            logger.error("Error converting audio file '%s' to wav", filename)
            logger.exception(ex)
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

        except RuntimeError as ex: # soundfile error
            logger.error("Error slicing audio file '%s'", filename)
            logger.exception(ex)
            return False, 0

    @staticmethod
    def decode_worker(dec_queue, stopping):
        try:
            while not stopping.value:
                try:
                    # block until next demod is in
                    next_demod = dec_queue.get(timeout=QUEUE_EMPTY_POLL_PERIOD)
                except Queue.Empty:
                    # check for stopped condition if queue empty after timeout
                    continue
                except KeyboardInterrupt:
                    return

                try:
                    wavfilename = next_demod["wavfilename"]
                    sample_rate, duration, nframes = DecoderQueue.get_audio_info(wavfilename)

                    # spawn the GNU radio flowgraph and run it
                    tb = equisat_fm_demod(wavfile=wavfilename, sample_rate=sample_rate)
                    logger.debug("[%s] Starting demod flowgraph" % wavfilename)
                    tb.start()
                    # run until the wav source block has completed
                    # (GNU Radio has a bug such that flowgraphs with Python message passing blocks won't terminate)
                    # (see https://github.com/gnuradio/gnuradio/pull/797, https://www.ruby-forum.com/t/run-to-completion-not-working-with-message-passing-blocks/240759)
                    while tb.blocks_wavfile_source_0.nitems_written(0) < nframes:
                        time.sleep(FLOWGRAPH_POLL_PERIOD_S)
                    logger.debug("[%s] Stopping demod flowgraph" % wavfilename)
                    tb.stop()
                    tb.wait()
                    logger.debug("[%s] Demod flowgraph terminated" % wavfilename)

                    # we have a block to store both all valid raw packets and one to store
                    # all those that passed error correction (which includes the corresponding raw)
                    raw_packets = []
                    corrected_packets = []

                    for i in range(tb.message_store_block_raw.num_messages()):
                        msg = tb.message_store_block_raw.get_message(i)
                        raw_packets.append(binascii.hexlify(bytearray(pmt.u8vector_elements(pmt.cdr(msg)))))

                    for i in range(tb.message_store_block_corrected.num_messages()):
                        msg = tb.message_store_block_corrected.get_message(i)
                        corrected = pmt.u8vector_elements(pmt.cdr(msg))
                        raw = pmt.u8vector_elements(pmt.dict_ref(pmt.car(msg), pmt.intern("raw"), pmt.get_PMT_NIL()))
                        decoded, decode_errs = packetparse.parse_packet(binascii.hexlify(bytearray(corrected)))
                        corrected_packets.append({
                            "raw": binascii.hexlify(bytearray(raw)),
                            "corrected": binascii.hexlify(bytearray(corrected)),
                            "parsed": decoded,
                            "decode_errs": decode_errs
                        })

                    onfinish = next_demod["onfinish"]
                    onfinish(wavfilename, {
                        "raw_packets": raw_packets,
                        "corrected_packets": corrected_packets,
                    }, next_demod["args"], None)

                except KeyboardInterrupt:
                    return
                except Exception as ex:
                    logger.error("Exception in decoder worker, skipping job")
                    logger.exception(ex)
                    onfinish = next_demod["onfinish"]
                    onfinish(next_demod["wavfilename"], {
                        "raw_packets": [],
                        "corrected_packets": [],
                    }, next_demod["args"], ex.message)

        finally:
            print("Stopping decoder worker")

def onfinish_cli(wf, packets, args, err):
    print("done; %d raw, %d corrected, err: %s" % (len(packets["raw_packets"]), len(packets["corrected_packets"]), err))

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: decoder.py <wavfilename>")
        exit(1)

    dec = DecoderQueue()
    dec.start(1)
    dec.submit(sys.argv[1], onfinish_cli, None)
    time.sleep(5)
    dec.stop()
