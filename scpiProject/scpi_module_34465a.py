#!/usr/bin/env python3

'''
Created on 2 Dec 2016

@author: keith

ScpiDevice Module for communication with LAN connected instruments
tested with Keysight 34465a multimeter

Notes:

R? reads and deletes data from the meter. If network is unreliable and a
network error occurs then we can have data loss.

FETC? (fetch) - waits until measurement is complete, then downloads then data.
As long as data series fits in memory (i.e. no more than 2000000 readings)
then this is probably a better method to use.

'''
import time
import socket
import sys
import os
import logging
from tqdm import tqdm

LOGGER = logging.getLogger(__name__)

HOST = '192.168.1.188'
PORT = 5025
DEBUG = True


class ScpiDevice:
    """ Class for sending messages to/from a SCPI device """
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.buffersize = 256
        self.socket_timeout = 10

        self.sock = None
        self.error = None
        self.connect()

    def connect(self):
        """ Connect to the device """
        # Try twice if first connection fails
        # If first attempt fails then wait 30s and retry
        conn = self._socket_connect()
        if not conn:
            LOGGER.error("Connection to socket failed. Will retry in 30s...")
            time.sleep(30)
            conn = self._socket_connect()
        return conn

    def _socket_connect(self):
        """ Attempt to connect to the socket """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.socket_timeout)

        try:
            self.sock.connect((self.host, self.port))
            return True
        except socket.error as err:
            self.error = "ERROR: Socket connection error. {}".format(err)
            LOGGER.error(self.error)
            return False

    def write(self, payload):
        """ Write to a device.  Payload must have a newline char.
        """
        # Must have a newline char
        payload = (payload + '\n').encode()
        try:
            self.sock.send(payload)
            self.error = None
            return True
        except socket.error as err:
            self.error = "ERROR: Socket send error. {}".format(err)
            return False

    def _read(self):
        """ Read from a device
        """
        resp_state = False
        resp_value = None
        try:
            resp_value = self.sock.recv(self.buffersize)
            self.error = None
            resp_state = True
        except socket.error as err:
            self.error = "ERROR: socket recieve error. {}".format(err)
            resp_value = None
            resp_state = False
        return resp_state, resp_value

    def get(self, payload):
        """ Get a given value from the scpi device
            Payload contains the wanted attribute that we aer wtrying to get
            So we send that command and then read back the value.
        """
        if not self.write(payload):
            resp_state = False
            resp_value = None
        else:
            resp_state, resp_value = self._read()
        return resp_state, resp_value

    def close(self):
        """ Close the socket """
        self.sock.close()


class Multimeter34465a(ScpiDevice):
    """ Class for handling Keysight 34465A Multimeter """
    def __init__(self, host, port):
        ScpiDevice.__init__(self, host, port)
        self.connect()

    def get_idn(self):
        """ Send *IDN? to get instrument identifier

        """
        return self.get('*IDN?')

    def get_conf(self):
        """ CONF?

            Returns a quoted string indicating the present function, range
            and resolution. The short form of the function name (CURR:AC, FREQ)
            is always returned.

        """
        return self.get('CONF?')

    def get_label(self):
        """ SYSTem:LABel?

            Places a message in a large font on the bottom half
            of the instrument's front panel display.

        """
        return self.get('SYSTem:LABel?')

    def get_meas_curr(self, m_ac_dc, m_range, m_res):
        """ MEASure:CURRent:{AC|DC}? [{<range>|AUTO|MIN|MAX|DEF}
                             [, {<resolution>|MIN|MAX|DEF}]]

            Sets all measurement parameters and trigger parameters to their
            default values for AC or DC current measurements and immediately
            triggers a measurement. The results are sent directly to the
            instrument's output buffer.

        """
        payload = "MEAS:CURR:{} {},{}".format(m_ac_dc, m_range, m_res)
        return self.get(payload)

    def get_format_data(self):
        """ FORMat[:DATA]?

            Returns the data format: either ASCII or REAL.

        """
        payload = "FORMat:DATA?"
        return self.get(payload)

    def get_std_op_reg(self):
        """ Get the reg value """
        reg_val = self.get("STAT:OPER:COND?")
        # LOGGER.debug(reg_val)
        return reg_val

    def get_std_op_reg_bit(self, bit_number):
        """ Get the required bit (true/false) from the reg """
        bit_mask = 1 << bit_number
        try:
            bit_val = int(self.get_std_op_reg()[1].decode().split("\n")[0])
            bit_val = bool(bit_val & bit_mask)
        except AttributeError:
            bit_val = None
        return bit_val

    def show_op_reg(self):
        """ Show the operating reg bit status
        """
        op_reg = int(self.get_std_op_reg()[1].decode())

        reg_vals = {0: 'Calibrating',
                    4: 'Measuring',
                    5: 'Waiting for trigger',
                    8: 'Configuration change',
                    9: 'Memory threshold',
                    10: 'Instrument locked',
                    13: 'Global error'
                    }

        LOGGER.debug("Standard Operation Register: %s", op_reg)
        for bit in reg_vals:
            bit_status = bool(op_reg & (1 << bit))
            message = "    {:20} = {}".format(reg_vals[bit], bit_status)
            LOGGER.debug(message)

    def get_error(self):
        """ SYSTem:ERRor?

        """
        payload = "SYSTem:ERRor?"
        return self.get(payload)

    def get_screen_dump(self, filename):
        """ HCOPy:SDUMp:DATA?

            Response is a file png or bmp delivered as bytes in an
            IEEE 488.2 definite-length block.

            A typical data block using the definite length format consists of:

            Start of data block
            | Number of digits in digits
            | |               Number of data bytes to be sent
            | |               |          Data bytes
            | |               |          |
            #<Non zero digit><len chars><file bytes>

            A typical example of a data block sending 2000 8-bit data bytes is:
            #42000<data bytes>

        """

        # if set_value(scpi_object, "HCOPy:SDUMp:DATA?"):
        if self.write("HCOPy:SDUMp:DATA?"):

            buff = self.sock.recv(256)

            # strip the header out
            num_digits = int(chr(buff[1]))
            file_size = int(buff[2:num_digits+2])
            buff = buff[2 + num_digits:]

            # Now grab the rest from the socket
            while len(buff) < file_size:
                buff = buff + self.sock.recv(256)

            with open(filename, 'wb') as file:
                # Remove the final '\n'
                file.write(buff[0:-1])
        else:
            return False
        return True

    def set_beep(self):
        """ SYSTem:BEEPer

            Issues a single beep.

        """
        payload = "SYST:BEEP"
        return self.write(payload)
        # return set_value(scpiObject, "SYST:BEEP")

    def set_trigger(self):
        """ Instruct meter to trigger measurement

        """
        payload = '*TRG'
        return self.write(payload)

    def set_conf_curr(self, m_ac_dc, m_range, m_res):
        """ CONFigure:CURRent:{AC|DC} [{<range>|AUTO|MIN|MAX|DEF}
                               [, {<resolution>|MIN|MAX|DEF}]]
            Sets all measurement parameters and trigger parameters to their
            default values for AC or DC current measurements. Also specifies
            the range and resolution.

        """
        payload = "CONF:CURR:{} {},{}".format(m_ac_dc, m_range, m_res)
        return self.write(payload)

    def set_label(self, payload):
        """ SYST:LAB "<string>"

            Places a message in a large font on the bottom half of the
            instrument's front panel display. Max 40chars

        """
        payload = 'SYST:LAB "{}"'.format(payload)
        return self.write(payload)

    def set_display_state(self, on_off_state):
        """ DISPlay[:STATe] {ON|1|OFF|0}

            Disables or enables the front panel display. When disabled,
            the display dims, and all annunciators are disabled. However,
            the screen remains on.

        """
        payload = "DISP:STAT {}".format(on_off_state)
        return self.write(payload)

    def reset(self):
        """ *RST

            Resets instrument to factory default state. This is similar to
            SYSTem:PRESet. The difference is that *RST resets the instrument
            for SCPI operation, and SYSTem:PRESet resets the instrument for
            front panel operation. As a result, *RST turns the histogram and
            statistics off, and SYSTem:PRESet turns them on.

        """
        payload = "*RST"
        return self.write(payload)

    def clear_registers(self):
        """ Clear Status Command.  Clears the event registers and error queue.
        """
        payload = "*CLS"
        return self.write(payload)

    def set_abort(self):
        """ ABORt

            Aborts a measurement in progress, returning the instrument to the
            trigger idle state.

        """
        payload = "ABORt"
        return self.write(payload)


def calc_34465a_aperture(duration):
    """ Calculates the minimum aperture for max number of samples
        Max samples = 2000000
        Min aperture = 22us
    """
    max_samples = 2000000
    min_aperture = 0.000022
    aperture = duration / max_samples
    aperture = min_aperture if aperture < min_aperture else aperture
    return aperture


def parse_block_header(block):
    """ Takes a byte string with a definiteLength header
        Returns the data_start position, num_expected_bytes, num_actual_bytes
        #512345<data>

    """
    try:
        num_digits = int(block[1:2])
        data_start = num_digits + 2
        num_expected_bytes = int(block[2:data_start])
        if block[-1:] == b'\n':
            num_actual_bytes = len(block[data_start:-1])
        else:
            num_actual_bytes = len(block[data_start:])
    except IndexError:
        print(block)
        sys.exit(1)
    return data_start, num_expected_bytes, num_actual_bytes


def read_data(device, filename, expected_points, progress=True):
    """ Meter is buffering data for us.  So we download it periodically.

        Read data using *R? command and save it to a file.
        Returns True if no errors.

        expected_points is the number of expected samples in the set

        read first block
        parse expected size & actual size
        loop until actual=expected

        extract final dataset and add it to data list

    """

    block_size = 10000
    buff_len = (block_size * 16) + 256

    # Setup the progress bar
    if progress:
        pbar = tqdm(total=expected_points)

    data_count = 0

    while data_count < expected_points:
        device.write('R? {}'.format(buff_len))
        block = b''
        try:
            while not block.endswith(b'\n'):
                block = device.sock.recv(buff_len)

        except socket.timeout:
            LOGGER.error('Socket timeout waiting for block data.')
            block = b''
            device.connect()

        if block == b'':
            LOGGER.error('No data received')

        else:

            data_start, num_expected_bytes, num_actual_bytes = \
                parse_block_header(block)

            # print(num_expected_bytes,num_actual_bytes)

            if num_expected_bytes != num_actual_bytes:
                LOGGER.error('Byte count error. Expected %s got %s',
                             num_actual_bytes,
                             num_actual_bytes)

            if num_expected_bytes != 0:
                block_list = block.decode().strip()[data_start:].split(',')
                data_count += len(block_list)
                if progress:
                    pbar.update(len(block_list))

                with open(filename, mode='a') as file:
                    for data_point in block_list:
                        file.write("{}\n".format(data_point))


def read_with_fetch(device, filename, expected_points,
                    test_duration, progress=True):
    """ Meter is buffering data for us, up to a max of 2000000 samples,
        Use FETC? to read all data once measurement is complete.
    """
    if expected_points > 2000000:
        print("Read_with_fetch only works with less than 2M samples. "
              "Try using read_data instead.")
        sys.exit(1)

    # Setup the progress bar
    if progress:
        pbar = tqdm(total=test_duration)

    # Triggger the instrument
    update_time = time.time()
    device.set_trigger()

    measuring_bit = 4
    while device.get_std_op_reg_bit(measuring_bit) in [True, None]:
        if progress:
            now_time = time.time()
            pbar.update(round(int(now_time - update_time)))
            update_time = now_time
        time.sleep(1)

    pbar.close()
    device.show_op_reg()

    # Measurement has finished so get the data
    get_existing_data(device, filename, expected_points)


def read_data_with_fetch(device):
    """ Read data back from the meter after measurement has completed

    """
    # Measurement has finished so get the data
    LOGGER.info("Downloading data from the meter...")

    device.write('FETC?')
    block = b''
    while not block.endswith(b'\n'):
        block += device.sock.recv(100000)

    data = block.decode().strip().split(",")
    LOGGER.info("Download done.  Number of Samples = %s", len(data))
    return data


def write_data_to_file(filename, data):
    """ Write data to a file with given name

    """
    with open(filename, mode='a') as file:
        for data_point in data:
            file.write("{}\n".format(data_point))
    LOGGER.info("Data written to file %s", filename)


def send_commands(meter, cmds):
    """ Takes a list of scpi cmds and sends them to the device
    """
    for cmd in cmds:
        write_state = meter.write(cmd)
        if write_state is False:
            LOGGER.error("Device write error.")

        # Also need to check that device has not generated an error
        # based on the last command
        error = meter.get_error()[1].decode().split(',')[1].strip()
        if error != '"No error"':
            print("***ERROR: {},{}".format(cmd, error))
            sys.exit(1)
            LOGGER.debug(error)


def current_measure_setup(meter, settings):
    """ Method to send the setup commands

        settings = {'curr_range': '10mA',
                    'apperture':   0.001,     # 1ms integration apperture
                    'num_samples': 1000000,
                    'sample_rate': 0.001,     # Sample every 1ms
                   }

    """
    # Configure the instrument to take the readings
    cmds = ['SENS:FUNC:ON "CURR:DC"',
            'CONF:CURR:DC {}'.format(settings['curr_range']),
            'SENS:CURR:DC:ZERO:AUTO OFF',
            'SENS:CURR:DC:APER {}'.format(settings['apperture']),
            'SAMP:COUNT {}'.format(settings['num_samples']),
            'TRIG:SOUR BUS',
            'SAMP:SOUR TIM',
            'SAMP:TIM {}'.format(settings['sample_rate']),
            'INIT']

    send_commands(meter, cmds)


def start_measurement(meter, measure, settings):
    """  Logs current using given parameters.
         Reset the meter, clear the registers, show the reg settings
         Program the meter settings for the test.
         Run the test and wait for completion.
         Download and save data to a file
    """
    print_settings(settings)

    LOGGER.info("Running a new test.")
    LOGGER.info("Resetting the multimeter...")
    meter.reset()
    meter.clear_registers()
    meter.show_op_reg()

    # Setup for the measurement
    if measure == "CURR":
        current_measure_setup(meter, settings)
    elif measure == 'VOLT':
        voltage_measure_setup(meter, settings)
    else:
        print('ERROR: measurement not recognised')
        sys.exit(1)

    duration = settings['num_samples'] * settings['sample_rate']
    LOGGER.info("Waiting for measurement to complete:")
    LOGGER.info("samples requested = %s", settings['num_samples'])
    LOGGER.info("test duration     = %ss", duration)

    # Trigger, wait for completion and download the data from the instrument
    LOGGER.info("Triggering the measurement...")
    read_with_fetch(meter,
                    settings['filename'],
                    settings['num_samples'],
                    duration)

    LOGGER.info("Test complete...")


def get_existing_data(meter, filename, num_samples):
    """ Get an existing dataset from the meter
    """
    data = read_data_with_fetch(meter)
    if len(data) != num_samples:
        LOGGER.error("Sample count error:  expected %s, got %s",
                     num_samples,
                     len(data))

        LOGGER.error("Data not saved to file")
    else:
        write_data_to_file(filename, data)


def voltage_measure_setup(meter, settings):
    """ Function to send the setup commands

        settings = {'curr_range': '10mA',
                    'apperture':   0.001,     # 1ms integration apperture
                    'num_samples': 1000000,
                    'sample_rate': 0.001,     # Sample every 1ms
                   }

    """
    # Configure the instrument to take the readings
    cmds = ['SENS:FUNC:ON "VOLT:DC"',
            'CONF:VOLT:DC {}'.format(settings['volt_range']),
            'SENS:VOLT:DC:ZERO:AUTO OFF',
            'SENS:VOLT:DC:APER {}'.format(settings['apperture']),
            'SAMP:COUNT {}'.format(settings['num_samples']),
            'TRIG:SOUR BUS',
            'SAMP:SOUR TIM',
            'SAMP:TIM {}'.format(settings['sample_rate']),
            'INIT']

    send_commands(meter, cmds)


def print_settings(settings):
    """ Print out the settings """
    for setting in settings:
        if isinstance(settings[setting], float):
            msg = "{:15}: {:f}".format(setting, settings[setting])
        else:
            msg = "{:15}: {}".format(setting, settings[setting])
        LOGGER.info(msg)


def main():
    """ Main Program """
    filename = '/tmp/junk.txt'
    if os.path.isfile(filename):
        LOGGER.error('File already exists')
        sys.exit(1)

    meter = Multimeter34465a(HOST, PORT)
    if meter.sock is None:
        print("No socket. Exit. {}".format(meter.error))
        sys.exit(1)
    else:
        print("Connected to:\n")
        print(meter.get_idn()[1].decode().strip())
        print("IP: {}\n".format(HOST))

    # Settings definition for the test
    # Notes:
    # Max number of samples is 2000000
    # Min apperture setting is 22us

    duration = 30  # Seconds
    aperture = calc_34465a_aperture(duration)

    sample_rate = aperture

    current_settings = {
        'curr_range': '100mA',
        'apperture': aperture,  # integration apperture
        'num_samples': int(duration / sample_rate),
        'sample_rate': sample_rate,
        'filename': filename
        }

    voltage_settings = {
        'volt_range': '100mV',
        'apperture': aperture,  # integration apperture
        'num_samples': int(duration / sample_rate),
        'sample_rate': sample_rate,
        'filename': filename
        }

    # Show the menu:

    my_prompt = (
        "Select an option:\n"
        "1: Make a new Current measurement\n"
        "2: Make a new Voltage measurement\n"
        "3: Download existing data from instrument\n"
        "X: Exit\n"
        )

    resp = input(my_prompt)

    if resp == '1':
        # Current logging test
        settings = current_settings
        start_measurement(meter, measure='CURR', settings=settings)
    elif resp == '2':
        settings = voltage_settings
        start_measurement(meter, measure='VOLT', settings=settings)
    elif resp == '3':
        get_existing_data(meter, filename, settings['num_samples'])
    else:
        pass

    # Shutdown
    meter.close()
    print("All done.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    main()
