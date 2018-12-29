from multiprocessing import Process, Queue, Value
from equisat_fm_demod import equisat_fm_demod
from packetparse import packetparse
import binascii
import pmt

class DecoderQueue:
    def __init__(self):
        self.queue = Queue()
        self.procs = []
        self.stopping = Value("b", False)

    def start(self, num):
        """ Spawns a new set of num processes which reads requests off the decode queue and performs them """
        for i in range(num):
            proc = Process(target=self.decode_worker, args=(self.queue, self.stopping))
            proc.start()
            self.procs.append(proc)

    def stop(self):
        self.stopping = True

    def submit(self, wavfilename, onfinish, args):
        """ Submits an FM decode job to the decoder queue."""
        self.queue.put_nowait({
            "wavfilename": wavfilename,
            "onfinish": onfinish,
            "args": args
        })

    @staticmethod
    def decode_worker(dec_queue, stopping):
        while not stopping.value:
            # block until next demod is in
            try:
                next_demod = dec_queue.get()
            except KeyboardInterrupt:
                print("Stopping decoder worker")
                return

            # determine sample rate of file
            # TODO
            sample_rate = None

            # spawn the GNU radio flowgraph and run it
            tb = equisat_fm_demod(next_demod["wavfilename"], sample_rate)
            tb.start()
            tb.wait()

            # we have a block to store both all valid raw packets and one to store
            # all those that passed error correction (which includes the corresponding raw)
            raw_packets = []
            corrected_packets = []

            for i in range(tb.message_store_block_raw.num_messages()):
                msg = tb.message_store_block_raw.get_message(i)
                raw_packets.append(pmt.u8vector_elements(pmt.cdr(msg)))

            for i in range(tb.message_store_block_corrected.num_messages()):
                msg = tb.message_store_block_corrected.get_message(i)
                corrected = pmt.u8vector_elements(pmt.cdr(msg))
                raw = pmt.u8vector_elements(pmt.dict_ref(pmt.car(msg), pmt.intern("raw"), pmt.get_PMT_NIL()))
                decoded, decode_errs = packetparse.parse_packet(binascii.hexlify(corrected))
                corrected_packets.append({
                    "raw": raw,
                    "corrected": corrected,
                    "decoded": decoded,
                    "decode_errs": decode_errs
                })

            onfinish = next_demod["onfinish"]
            onfinish({
                "raw_packets": raw_packets,
                "corrected_packets": corrected_packets,
            }, next_demod["args"])
