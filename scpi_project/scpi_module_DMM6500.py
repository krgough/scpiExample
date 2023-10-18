#!/usr/bin/env python3

'''
Created on 17th Oct 2023

@author: keith

ScpiDevice Module for communication with LAN connected instruments
tested with Keysight DMM6500 multimeter

'''

# Note (from 34465a - may not apply to the DMM6500)s:
#
# R? reads and deletes data from the meter. If network is unreliable and a
# network error occurs then we can have data loss.
#
# FETC? (fetch) - waits until measurement is complete, then downloads data.
# As long as data series fits in memory (i.e. no more than 2000000 readings)
# then this is probably a better method to use.

import argparse
import time
import datetime
import socket
import sys
import os
import logging


LOGGER = logging.getLogger(__name__)

IP_ADDR = "192.168.1.45"
PORT = 5025
DATAFILE = 'meter_data'
BUFFER_NAME = "kgbuffer"


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
            print(f"Attempt {attempts} of {max_attempts}. "
                  "Connection to socket failed. Will retry in 30s...")
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
            self.error = f"ERROR: Socket connection error. {err}"
            print(self.error)
            return False

    def _write(self, payload):
        """ Write to a device.  Payload must have a newline char.
        """
        # Must have a newline char
        payload = (payload + '\n').encode()
        try:
            self.sock.send(payload)
            self.error = None
            return True
        except socket.error as err:
            self.error = f"ERROR: Socket send error: {err}"
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
            self.error = f"ERROR: socket receive error: {err}"
            LOGGER.debug(self.error)
            resp_value = None
            resp_state = False
        return resp_state, resp_value

    def get(self, payload):
        """ Get a given value from the scpi device
            Payload contains the wanted attribute that we are trying to get
            So we send that command and then read back the value.
        """
        if not self._write(payload):
            resp_state = False
            resp_value = None
        else:
            resp_state, resp_value = self._read()
        return resp_state, resp_value

    def close(self):
        """ Close the socket """
        self.sock.close()


class MultimeterDMM6500(ScpiDevice):
    """ Class for handling Keithly DMM6500 Multimeter """
    def __init__(self, host, port):
        ScpiDevice.__init__(self, host, port)

    def send_commands(self, cmds):
        """Send the commands and check for errors"""

        if cmds.__class__ is not list:
            cmds = [cmds]

        for cmd in cmds:
            LOGGER.info("Sending command: %s", cmd)
            self._write(":SYSTem:CLEar")
            write_state = self._write(cmd)
            if write_state is False:
                raise CommandError(self.error)

            # Also check that device has not generated an error
            # based on the last command
            error = self.get_error()[1].decode().split(',')[1].strip()
            if "No error" not in error:
                msg = f"Command Error in send_commands: {cmd},{error}"
                raise CommandError(msg)

    def get_idn(self):
        """ Send *IDN? to get instrument identifier

        """
        return self.get('*IDN?')

    def get_meas_curr(self, m_ac_dc, m_range):
        """ Sets measurement parameters and immediately triggers a measurement.
        """
        # payload = f"MEAS:CURR:{m_ac_dc} {m_range},{m_res}?"
        if m_range not in ["10e-6", "100e-6", "1e-3", "10e-3", "100e-3", "1", "3", "10"]:
            raise ValueError("Invalid range value for current measurement")
        if m_ac_dc not in ["AC", "DC"]:
            raise ValueError("Invalid AC/DC value for current measurement")
        self.send_commands(f':SENS:CURR:RANG {m_range}')
        return self.get(f'MEAS:CURR:{m_ac_dc}?')

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
        for bit, title in reg_vals.items():
            bit_status = bool(op_reg & (1 << bit))
            message = f"    {title:20} = {bit_status}"
            LOGGER.info(message)

    def get_error(self):
        """ :SYSTem:ERRor:NEXT? """
        return self.get(":SYSTem:ERRor:NEXT?")

    def set_beep(self, freq=500, duration=0.2):
        """ SYSTem:BEEPer
            Issues a single beep.
        """
        return self.send_commands(f"SYST:BEEP {freq},{duration}")

    def set_trigger(self):
        """ Instruct meter to trigger measurement"""
        return self.send_commands('*TRG')

    def disp_text(self, line, payload):
        """ DISPlay:USER<n>:TEXT[:DATA] "text message" """
        return self.send_commands(f':DISP:USER{line}:TEXT "{payload}"')

    def disp_clear(self):
        """ :DISP:CLE
            Clear the user display
        """
        return self.send_commands(":DISP:CLE")

    def reset(self):
        """ *RST

            Resets instrument to factory default state.
        """
        return self.send_commands("*RST")

    def clear_registers(self):
        """Clear Status Command.  Clears the event registers and error queue."""
        return self.send_commands("*CLS")

    def set_abort(self):
        """ ABORt

            Aborts a measurement in progress, returning the instrument to the
            trigger idle state.

        """
        return self.send_commands("ABORt")

    def read_data(self, buffer):
        """Read data back from the meter after measurement has completed"""
        # Measurement has finished so get the data
        LOGGER.info("Downloading data from the meter...")

        # data = self.get(f':TRACE:DATA? 1, 10000, "{buffer}"')
        last_index = self.get(f':TRACe:ACTual:END? "{buffer}"')[1].decode().strip()
        data = self._write(f':TRACE:DATA? 1, {last_index}, "{buffer}"')
        block = b''
        while not block.endswith(b'\n'):
            block += self.sock.recv(1000000)

        data = block.decode().strip().replace("\n", ",")
        data = data.split(",")
        data = [float(x) for x in data]
        LOGGER.info("Download done.  Number of Samples = %s", len(data))

        return data

    def current_measure_setup(self, settings):
        """Method to send the setup commands for current measurements """
        # Configure the instrument to take the readings
        cmds = [
            ':SENS:DIG:FUNC "CURR"',
            ':TRACe:POINts 10, "defbuffer1"',
            ':TRACe:POINts 10, "defbuffer2"',
            f':TRACe:MAKE "{settings["buffer"]}", {settings["count"]}',
            f':SENS:DIG:CURR:RANG {settings["range"]}',
            f':SENS:DIG:CURR:SRATE {settings["sample_rate"]}',
            f':SENS:DIG:COUN {settings["count"]}',
        ]
        self.send_commands(cmds)

        # Trigger the measurement
        start_time = time.time()
        self._write(f':TRACe:TRIG:DIG "{settings["buffer"]}"')

        # Wait for the expected measurement duration
        timeout = start_time + (settings['count'] // settings['sample_rate']) + 10
        LOGGER.info(
            "Waiting for measurement to complete. Estimated finish time: %s",
            datetime.datetime.fromtimestamp(timeout).strftime('%Y-%m-%d %H:%M:%S')
         )

        while time.time() < timeout:
            time.sleep(10)
            res = self.get_idn()
            if res[0] is True:
                LOGGER.info("Measurement complete")
                return True

        LOGGER.error("Measurement timeout")
        return False

    def current_measurement(self, settings):
        """Execute the current measurement and save the results to a file"""
        measurement_done = self.current_measure_setup(settings)
        if measurement_done:
            data = self.read_data(buffer=settings['buffer'])
            filename = get_filename()
            print(f"Averge current: {format(sum(data) / len(data))}")
            save_data_to_file(data=data, filename=filename)

    def voltage_measure_setup(self, settings):
        """ Function to send the setup commands for voltage measurements

        """
        # Configure the instrument to take the readings
        num_samples = settings['duration'] / settings['sample_rate']
        cmds = [
            'SENS:FUNC:ON "VOLT:DC"',
            f'CONF:VOLT:DC {settings["volt_range"]}',
            'SENS:VOLT:DC:ZERO:AUTO OFF',
            f'SENS:VOLT:DC:APER {settings["aperture"]}',
            f'SAMP:COUNT {num_samples}',
            'TRIG:SOUR BUS',
            'SAMP:SOUR TIM',
            f'SAMP:TIM {settings["sample_rate"]}',
            'INIT'
        ]

        self.send_commands(cmds)

    def voltage_measurement(self, settings):
        """Execute the voltage measurement and save the results to a file"""
        LOGGER.error("Voltage measurement not implemented yet")


def get_filename():
    """Create a unique filename for the data file"""
    return f'{DATAFILE}{datetime.datetime.now().strftime("%Y%m%dT%H%M%S")}.txt'


def save_data_to_file(filename, data):
    """ Write data to a file with given name"""
    with open(filename, mode='a', encoding='utf-8') as file:
        for data_point in data:
            file.write(f"{data_point}\n")
    LOGGER.info("Data written to file %s", filename)


def file_exists(settings):
    """ Abort if file already exists
    """
    if os.path.isfile(settings['filename']):
        print(f'File {settings["filename"]} already exists')
        input("Hit any key to continue...\n")
        return True
    return False


def get_meter(settings):
    """ Connect to the meter
    """
    meter = MultimeterDMM6500(settings['ip_addr'], settings['port'])
    if meter.sock is None:
        print(f"No socket. Exit. {meter.error}")
        sys.exit(1)
    else:
        msg = meter.get_idn()[1].decode().strip()
        print(f"Connected to: {msg}".format(msg))
        print(f"IP: {settings['ip_addr']}\n")
    return meter


def handle_download(args):
    """Download data from the meter buffer and save to a file"""
    meter = get_meter(settings={"ip_addr": args.ip_address, "port": PORT})
    data = meter.read_data(buffer=BUFFER_NAME)
    filename = get_filename()
    print(f"Averge current: {format(sum(data) / len(data))}")
    save_data_to_file(data=data, filename=filename)


def handle_measurement(args):
    """Setup and trigger a measurement.  Data saved to a buffer on the device"""
    settings = {
        'count': args.samples,
        "sample_rate": args.rate,
        "range": args.measurement_range,
        "buffer": BUFFER_NAME
    }

    meter = get_meter(settings={"ip_addr": args.ip_address, "port": PORT})

    if args.voltage:
        meter.reset()
        meter.voltage_measurement(settings)
    elif args.current:
        meter.reset()
        meter.current_measurement(settings)


def get_args():
    """Get the command line arguments and run the required measurement"""
    msg = "Utility to drive DMM6550 keysight multimeter."

    parser = argparse.ArgumentParser(description=msg)

    parser.add_argument(
        "-i", "--ip-address",
        required=True,
        type=str,
        help="IP Address of the meter"
    )

    subparsers = parser.add_subparsers(help="Subcommands:")

    download_parser = subparsers.add_parser("download", help="Download data from the meter")
    download_parser.set_defaults(func=handle_download)

    measurement_parser = subparsers.add_parser("measurement", help="Measurement type")
    measurement_parser.set_defaults(func=handle_measurement)
    measurement_group = measurement_parser.add_mutually_exclusive_group()
    measurement_group.add_argument(
        "-v", "--voltage",
        action="store_true",
        help="DC Voltage measurement"
    )
    measurement_group.add_argument(
        "-c", "--current",
        action="store_true",
        help="DC Current measurement"
    )
    measurement_parser.add_argument(
        "-m", "--measurement_range",
        type=str,
        required=True,
        help="Measurement range e.g. 100e-3"
    )
    measurement_parser.add_argument(
        "-r", "--rate",
        type=int,
        required=True,
        help="Sample rate for the measurement"
    )
    measurement_parser.add_argument(
        "-n", "--samples",
        required=True,
        type=int,
        help="Number of samples to take"
    )

    return parser.parse_args()


def test_commands():
    """Test that all the meter commands are working"""
    settings = {
       "ip_addr": IP_ADDR,
       "port": PORT
    }

    meter = get_meter(settings)
    # print(f"Meter IDN: {meter.get_idn()}")
    print(f"Meter Reset: {meter.reset()}")
    time.sleep(1)
    # print(f'Measure Current: {meter.get_meas_curr("DC", "3")}')
    # print(f"Data Format: {meter.get_format_data()}")
    # print(f"Standard Operation Register: {meter.get_std_op_reg()}")
    # print("WARNING: THESE reister values may not be correct.  They are for another meter")
    # meter.show_op_reg()
    # meter.set_beep()
    # meter.set_trigger()
    # meter.disp_text(1, "Keef was ere")
    # meter.disp_text(2, "Oh yeah Baby")
    # time.sleep(1)
    # meter.disp_clear()
    # meter.clear_registers()
    # meter.set_abort()
    settings = {'count': 25000, "sample_rate": 1000, "range": "100e-3", "buffer": "kgbuffer"}
    meter.current_measure_setup(settings=settings)
    data = meter.read_data(buffer=settings['buffer'])
    filename = get_filename()
    print(f"Averge current: {format(sum(data) / len(data))}")
    LOGGER.info("Saving date to file: %s", filename)
    save_data_to_file(data=data, filename=filename)

    print("All done")


def main():
    """Entry Point"""
    # test_commands()
    # exit()

    args = get_args()
    args.func(args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
