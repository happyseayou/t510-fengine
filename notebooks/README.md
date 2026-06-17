# Notebook Skeletons

Recommended notebook sequence:

1. `00_board_check.ipynb`
2. `01_clock_lmk_check.ipynb`
3. `02_rfdc_snapshot.ipynb`
4. `03_rfdc_spectrum.ipynb`
5. `04_pfb_tone_test.ipynb`
6. `05_udp_packet_test.ipynb`
7. `06_spec_stream_run.ipynb`
8. `07_time_stream_run.ipynb`
9. `08_lab_rfdc_fft_debug.ipynb`

The repository ships these as minimal templates so the overlay API and bring-up flow stay stable while the board-specific data movers are completed.

`08_lab_rfdc_fft_debug.ipynb` is the current hands-on RFDC bring-up notebook for the no-PPS/no-external-10MHz lab setup. It loads the latest overlay, switches to `tcxo_10mhz + free_run`, and exposes ADC0 time waveform plus hardware FFT debug spectrum through interactive buttons.
