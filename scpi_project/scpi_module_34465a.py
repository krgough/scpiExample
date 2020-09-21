#!/usr/bin/env python3

'''
Created on 2 Dec 2016

@author: keith

ScpiDevice Module for communication with LAN connected instruments
tested with Keysight 34465a multimeter

'''

# Notes:
#
# R? reads and deletes data from the meter. If network is unreliable and a
# network error occurs then we can have data loss.
#
# FETC? (fetch) - waits until measurement is complete, then downloads data.
# As long as data series fits in memory (i.e. no more than 2000000 readings)
# then this is probably a better method to use.


import time
import socket
import sys
import os
import logging
import pickle
from tqdm import tqdm

LOGGER = logging.getLogger(__name__)

HOST = '192.168.1.188'
PORT = 5025
CONFIG_FILE = 'config.cfg'


class CommandError(Exception):
    """ Exception for errors when sending cmds to the meter """


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
        print("\nAttempting to connect to meter...")
        conn = self._socket_connect()
        attempts = 1
        max_attempts = 5
        if not conn and attempts < max_attempts:
            print("Attempt {} of {}. "
                  "Connection to socket failed. Will retry in 30s...".format(
                      attempts, max_attempts))
            time.sleep(30)
            attempts += 1
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
            print(self.error)
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
    except IndexError as err:
        msg = "Index error in parse_clock_header(). {}".format(block)
        raise IndexError(msg) from err

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
            print('Socket timeout waiting for block data.')
            block = b''
            device.connect()

        if block == b'':
            print('No data received')

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


def trigger_and_fetch(device, settings, progress=True):
    """ Meter is buffering data for us, up to a max of 2000000 samples,
        Use FETC? to read all data once measurement is complete.
    """
    num_samples = int(settings['duration'] / settings['sample_rate'])
    if num_samples > 2000000:
        print("Read_with_fetch only works with less than 2M samples. "
              "Try using read_data instead.")
        return

    # Setup the progress bar
    if progress:
        pbar = tqdm(total=settings['duration'])

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
    get_existing_data(settings)


def read_data_with_fetch(device):
    """ Read data back from the meter after measurement has completed

    """
    # Measurement has finished so get the data
    print("Downloading data from the meter...")

    device.write('FETC?')
    block = b''
    while not block.endswith(b'\n'):
        block += device.sock.recv(100000)

    data = block.decode().strip().split(",")
    print("Download done.  Number of Samples = {}".format(len(data)))
    return data


def write_data_to_file(filename, data):
    """ Write data to a file with given name

    """
    with open(filename, mode='a') as file:
        for data_point in data:
            file.write("{}\n".format(data_point))
    print("Data written to file {}".format(filename))


def send_commands(meter, cmds):
    """ Takes a list of scpi cmds and sends them to the device
    """
    for cmd in cmds:
        write_state = meter.write(cmd)
        if write_state is False:
            raise CommandError("Device write error in send_commands()")

        # Also need to check that device has not generated an error
        # based on the last command
        error = meter.get_error()[1].decode().split(',')[1].strip()
        if error != '"No error"':
            msg = "Command Error in send_commands: {},{}".format(cmd, error)
            raise CommandError(msg)


def current_measure_setup(meter, settings):
    """ Method to send the setup commands for current measurements
    """
    # Configure the instrument to take the readings
    num_samples = settings['duration'] / settings['sample_rate']
    cmds = ['SENS:FUNC:ON "CURR:DC"',
            'CONF:CURR:DC {}'.format(settings['curr_range']),
            'SENS:CURR:DC:ZERO:AUTO OFF',
            'SENS:CURR:DC:APER {}'.format(settings['aperture']),
            'SAMP:COUNT {}'.format(num_samples),
            'TRIG:SOUR BUS',
            'SAMP:SOUR TIM',
            'SAMP:TIM {}'.format(settings['sample_rate']),
            'INIT']

    send_commands(meter, cmds)


def voltage_measure_setup(meter, settings):
    """ Function to send the setup commands for voltage measurements

    """
    # Configure the instrument to take the readings
    num_samples = settings['duration'] / settings['sample_rate']
    cmds = ['SENS:FUNC:ON "VOLT:DC"',
            'CONF:VOLT:DC {}'.format(settings['volt_range']),
            'SENS:VOLT:DC:ZERO:AUTO OFF',
            'SENS:VOLT:DC:APER {}'.format(settings['aperture']),
            'SAMP:COUNT {}'.format(num_samples),
            'TRIG:SOUR BUS',
            'SAMP:SOUR TIM',
            'SAMP:TIM {}'.format(settings['sample_rate']),
            'INIT']

    send_commands(meter, cmds)


def file_exists(settings):
    """ Abort if file already exists
    """
    if os.path.isfile(settings['filename']):
        print('File {} already exists'.format(settings['filename']))
        input("Hit any key to continue...\n")
        return True
    return False


def get_meter(settings):
    """ Connect to the meter
    """
    meter = Multimeter34465a(settings['ip_addr'], settings['port'])
    if meter.sock is None:
        print("No socket. Exit. {}".format(meter.error))
        sys.exit(1)
    else:
        print("Connected to:\n")
        print(meter.get_idn()[1].decode().strip())
        print("IP: {}\n".format(settings['ip_addr']))
    return meter


def start_measurement(measure, settings):
    """  Logs current using given parameters.
         Reset the meter, clear the registers, show the reg settings
         Program the meter settings for the test.
         Run the test and wait for completion.
         Download and save data to a file
    """
    if file_exists(settings):
        return

    meter = get_meter(settings)

    print("Running a new test.")
    print("Resetting the multimeter...")
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
        meter.close()
        return

    num_samples = int(settings['duration'] / settings['sample_rate'])
    print("Waiting for measurement to complete:")
    print("samples requested = {}".format(num_samples))
    print("test duration     = {}s".format(settings['duration']))

    # Trigger, wait for completion and download the data from the instrument
    print("Triggering the measurement...")
    trigger_and_fetch(meter, settings)

    print("Test complete...")
    meter.close()


def get_existing_data(settings):
    """ Get an existing dataset from the meter
    """
    if file_exists(settings):
        return
    meter = get_meter(settings)

    data = read_data_with_fetch(meter)

    num_samples = int(settings['duration'] / settings['sample_rate'])

    if len(data) != num_samples:
        print("Sample count error:  expected {}, got {}".format(num_samples,
                                                                len(data)))

        print("Data not saved to file")
    else:
        write_data_to_file(settings['filename'], data)
    meter.close()


def print_settings(settings):
    """ Print out the settings """
    for setting in settings:
        if isinstance(settings[setting], float):
            msg = "{:15}: {:f}".format(setting, settings[setting])
        else:
            msg = "{:15}: {}".format(setting, settings[setting])
        print(msg)


def load_settings(default=False):
    """ Returns the settings to use for the test

        If default is TRUE:
            return the default settings
        Else:
            If a default file exists
                return settings from the file
            Else:
                return default settings

    # if yes then load it
    # else use defaults
    # Allow use to force use of defaults.
    """
    # Default Settings definitions
    filename = '/tmp/junk.txt'
    duration = 30

    # Integration Aperture
    aperture = calc_34465a_aperture(duration)

    # Set the default sample rate to same period as integration aperture
    sample_rate = aperture

    default_settings = {
        'ip_addr': HOST,
        'port': PORT,
        'curr_range': '100mA',
        'volt_range': '100mV',
        'duration': duration,
        'aperture': aperture,
        'sample_rate': sample_rate,
        'filename': filename,
        }

    if default:
        return default_settings

    try:
        with open(CONFIG_FILE, "rb") as file:
            settings = pickle.load(file)
    except FileNotFoundError:
        settings = default_settings

    return settings


def save_settings(settings):
    """ Pickle settings into the config file
    """
    with open(CONFIG_FILE, 'wb') as file:
        pickle.dump(settings, file)


def main():
    """ Allow user to select new settings and start the measurement

    """
    settings = load_settings()

    while True:
        fields = ['ip_addr', 'port', 'curr_range', 'volt_range', 'duration',
                  'aperture', 'sample_rate', 'filename']

        values = [settings[field] for field in fields]

        print("Choose an attribute to modify or 's' to start the measurement:")
        for idx, field in enumerate(fields):
            value = values[idx]
            if isinstance(value, float):
                value = "{:f}".format(value)
            print("{:2}) {:12}: {}".format(idx + 1, field, value))
        print(" d) Reset to default settings")
        print(" c) Start current measurement")
        print(" v) Start voltage measurement")
        print(" e) Get existing data from meter")
        print(" x) Exit\n")

        resp = input("Select an option: ")

        # Handle attribute changes
        if resp in ['1', '2', '3', '4', '5', '6', '7', '8', '9']:
            idx = int(resp) - 1
            field = fields[idx]
            old_val = values[idx]
            new_val = input("{} = ".format(field))

            try:
                new_val = type(old_val)(new_val)
                settings[field] = new_val
                with open(CONFIG_FILE, 'wb') as file:
                    pickle.dump(settings, file)
            except ValueError:
                print('Wrong data type.  Try again.\n')

        elif resp == 'd':
            settings = load_settings(default=True)

        elif resp == 'c':
            start_measurement(measure='CURR', settings=settings)

        elif resp == 'v':
            start_measurement(measure='VOLT', settings=settings)

        elif resp == 'e':
            get_existing_data(settings)

        elif resp == 'x':
            print('All done.')
            return


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    main()
