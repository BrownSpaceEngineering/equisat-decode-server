#!/usr/bin/env python2
# -*- coding: utf-8 -*-
##################################################
# GNU Radio Python Flow Graph
# Title: Equisat Fm Demod
# Description: This flowgraph generates the flowgraph used in decode.py
# Generated: Sun Dec 30 16:07:39 2018
##################################################


from gnuradio import blocks
from gnuradio import digital
from gnuradio import eng_notation
from gnuradio import filter
from gnuradio import gr
from gnuradio.eng_option import eng_option
from gnuradio.filter import firdes
from optparse import OptionParser
import equisat_decoder


class equisat_fm_demod(gr.top_block):

    def __init__(self, sample_rate=48000, wavfile=""):
        gr.top_block.__init__(self, "Equisat Fm Demod")

        ##################################################
        # Parameters
        ##################################################
        self.sample_rate = sample_rate
        self.wavfile = wavfile

        ##################################################
        # Variables
        ##################################################
        self.gain_mu = gain_mu = 0.550

        ##################################################
        # Blocks
        ##################################################
        self.message_store_block_raw = blocks.message_debug()
        self.message_store_block_corrected = blocks.message_debug()
        self.low_pass_filter_0 = filter.fir_filter_fff(1, firdes.low_pass(
        	1, sample_rate, 4800, 1000, firdes.WIN_HAMMING, 6.76))
        self.equisat_decoder_equisat_fec_decoder_0 = equisat_decoder.equisat_fec_decoder()
        self.equisat_decoder_equisat_4fsk_preamble_detect_0 = equisat_decoder.equisat_4fsk_preamble_detect(255,0.33, 96)
        self.equisat_decoder_equisat_4fsk_block_decode_0 = equisat_decoder.equisat_4fsk_block_decode(255, False)
        self.digital_clock_recovery_mm_xx_0 = digital.clock_recovery_mm_ff(sample_rate/4800.0, 0.25*gain_mu*gain_mu, 0.5, gain_mu, 0.005)
        self.blocks_wavfile_source_0 = blocks.wavfile_source(wavfile, False)
        self.blocks_multiply_const_vxx_0_0 = blocks.multiply_const_vff((10, ))

        ##################################################
        # Connections
        ##################################################
        self.msg_connect((self.equisat_decoder_equisat_4fsk_block_decode_0, 'out'), (self.equisat_decoder_equisat_fec_decoder_0, 'in'))
        self.msg_connect((self.equisat_decoder_equisat_4fsk_block_decode_0, 'out'), (self.message_store_block_raw, 'store'))
        self.msg_connect((self.equisat_decoder_equisat_4fsk_preamble_detect_0, 'out'), (self.equisat_decoder_equisat_4fsk_block_decode_0, 'in'))
        self.msg_connect((self.equisat_decoder_equisat_fec_decoder_0, 'out'), (self.message_store_block_corrected, 'store'))
        self.connect((self.blocks_multiply_const_vxx_0_0, 0), (self.low_pass_filter_0, 0))
        self.connect((self.blocks_wavfile_source_0, 0), (self.blocks_multiply_const_vxx_0_0, 0))
        self.connect((self.digital_clock_recovery_mm_xx_0, 0), (self.equisat_decoder_equisat_4fsk_preamble_detect_0, 0))
        self.connect((self.low_pass_filter_0, 0), (self.digital_clock_recovery_mm_xx_0, 0))

    def get_sample_rate(self):
        return self.sample_rate

    def set_sample_rate(self, sample_rate):
        self.sample_rate = sample_rate
        self.low_pass_filter_0.set_taps(firdes.low_pass(1, self.sample_rate, 4800, 1000, firdes.WIN_HAMMING, 6.76))
        self.digital_clock_recovery_mm_xx_0.set_omega(self.sample_rate/4800.0)

    def get_wavfile(self):
        return self.wavfile

    def set_wavfile(self, wavfile):
        self.wavfile = wavfile

    def get_gain_mu(self):
        return self.gain_mu

    def set_gain_mu(self, gain_mu):
        self.gain_mu = gain_mu
        self.digital_clock_recovery_mm_xx_0.set_gain_omega(0.25*self.gain_mu*self.gain_mu)
        self.digital_clock_recovery_mm_xx_0.set_gain_mu(self.gain_mu)


def argument_parser():
    description = 'This flowgraph generates the flowgraph used in decode.py'
    parser = OptionParser(usage="%prog: [options]", option_class=eng_option, description=description)
    parser.add_option(
        "", "--sample-rate", dest="sample_rate", type="intx", default=48000,
        help="Set Sample Rate [default=%default]")
    parser.add_option(
        "", "--wavfile", dest="wavfile", type="string", default="",
        help="Set Input WAV File [default=%default]")
    return parser


def main(top_block_cls=equisat_fm_demod, options=None):
    if options is None:
        options, _ = argument_parser().parse_args()

    tb = top_block_cls(sample_rate=options.sample_rate, wavfile=options.wavfile)
    tb.start()
    tb.wait()


if __name__ == '__main__':
    main()
