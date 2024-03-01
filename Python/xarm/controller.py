from .servo import Servo
from .util import Util
import time


class Controller:
    SIGNATURE               = 0x55
    CMD_SERVO_MOVE          = 0x03
    CMD_GET_BATTERY_VOLTAGE = 0x0f
    CMD_SERVO_STOP          = 0x14
    CMD_GET_SERVO_POSITION  = 0x15
    CMD_SERVO_ID_WRITE      = 0x1b

    def __init__(self, com_port, debug=False, usb_path=None):
        if com_port.startswith('COM'):
            import serial
            self._device = serial.Serial(com_port, 9600, timeout=1)
            self._is_serial = True
        elif com_port.startswith('USB'):
            import hid
            self._device = hid.device()
            serial_number = com_port.strip('USB')
            if serial_number:
                self._device.open(0x0483, 0x5750, serial_number)
            elif usb_path is not None:
                self._device.open_path(bytes(usb_path, 'utf-8'))
            else:
                self._device.open(0x0483, 0x5750)
            self._device.set_nonblocking(1)
            if debug:
                print('Serial number:', self._device.get_serial_number_string())
            self._usb_recv_event = False
            self._is_serial = False
        else:
            raise ValueError('com_port parameter incorrect.')
        self.debug = debug
        self._input_report = []
        self.servos = []

    def setPosition(self, servos, position=None, duration=1000, wait=False):
        data = bytearray([1, duration & 0xff, (duration & 0xff00) >> 8])

        if isinstance(servos, int) or isinstance(servos, float):
            if position == None:
                raise ValueError('Parameter \'position\' missing.')
            if isinstance(position, int):
                if position < 0 or position > 1000:
                    raise ValueError('Parameter \'position\' must be between 0 and 1000.')
            if isinstance(position, float):
                if position < -125.0 or position > 125.0:
                    raise ValueError('Parameter \'position\' must be between -125.0 and 125.0.')
                position = Util._angle_to_position(position)
            data.extend([servos, position & 0xff, (position & 0xff00) >> 8])
        elif isinstance(servos, Servo):
            data.extend([servos.servo_id, servos.position & 0xff, (servos.position & 0xff00) >> 8])
        elif isinstance(servos, list):
            data[0] = len(servos)
            for servo in servos:            
                if isinstance(servo, Servo):
                    data.extend([servo.servo_id, servo.position & 0xff, (servo.position & 0xff00) >> 8])
                elif len(servo) == 2 and isinstance(servo[0], int):
                    if isinstance(servo[1], int):
                        if servo[1] < 0 or servo[1] > 1000:
                            raise ValueError('Parameter \'position\' must be between 0 and 1000.')
                        position = servo[1]
                    elif isinstance(servo[1], float):
                        if servo[1] < -125.0 or servo[1] > 125.0:
                            raise ValueError('Parameter \'position\' must be between -125.0 and 125.0.')
                        position = Util._angle_to_position(servo[1])
                    data.extend([servo[0], position & 0xff, (position & 0xff00) >> 8])
                else:
                    raise ValueError('Parameter list \'servos\' is not valid.')
        else:
            raise ValueError('Parameter \'servos\' is not valid.')

        self._send(self.CMD_SERVO_MOVE, data)

        if wait:
            time.sleep(duration/1000)

    def getPosition(self, servos, degrees=False):
        if isinstance(servos, int):
            data = bytearray([1, servos])
        elif isinstance(servos, Servo):
            data = bytearray([1, servos.servo_id])
        elif isinstance(servos, list) and all(isinstance(x, Servo) for x in servos):
            data = bytearray([len(servos)])
            for servo in servos:
                data.append(servo.servo_id)
        else:
            raise ValueError('Parameter \'servos\' is not valid.')

        self._send(self.CMD_GET_SERVO_POSITION, data)

        data = self._recv(self.CMD_GET_SERVO_POSITION)

        if data != None:
            if isinstance(servos, list):
                for i in range(data[0]):
                    servos[i].position = data[i*3+3] * 256 + data[i*3+2]
            else:
                position = data[3] * 256 + data[2]
                return Util._position_to_angle(position) if degrees else position
        else:
            raise Exception('Function \'getPosition\' recv error.')

    def servoOff(self, servos=None):
        data = bytearray([1])

        if isinstance(servos, int):
            data.append(servos)
        elif isinstance(servos, Servo):
            data.append(servos.servo_id)
        elif isinstance(servos, list):
            data[0] = len(servos)
            for servo in servos:
                if isinstance(servo, int):
                    data.append(servo)
                elif isinstance(servo, Servo):
                    data.append(servo.servo_id)
        elif servos is None:
            data = [6, 1,2,3,4,5,6]
        else:
            raise ValueError('servos parameter incorrect.')

        self._send(self.CMD_SERVO_STOP, data)

    # NOTE: the BusServoInfoWrite (0x1b) command passes the write command to *all* servos.
    # if the desire is to update only one servo_id, you must physically connect only
    # that servo. if you are doing a mass update of servos to the same id, then you
    # can pass overwrite_all_servo_ids=True to state your intention
    def writeServoId(self, new_servo_id=0, overwrite_all_servo_ids=False):
        # listing servos is an expensive operation, so we only do it when needing to perform a sanity check
        if not overwrite_all_servo_ids:
            self.listServos()

        if len(self.servos) == 0:
            raise ValueError("No servos to update their id")

        if len(self.servos) > 1 and not overwrite_all_servo_ids:
            raise ValueError(
                "More than one servo is connected. Pass overwrite_all_servo_ids=True to write the same servo_id to all connected servos, or connect only one servo physically at a time to update its id")

        if new_servo_id == 0:
            raise ValueError('new_servo_id must be non-zero', new_servo_id)

        data = bytearray([new_servo_id])
        self._send(self.CMD_SERVO_ID_WRITE, data)

    def listServos(self, maximum_servo_id=6):
        self.servos = []
        for i in range(1, maximum_servo_id + 1):
            try:
                self.getPosition(i)
                self.servos.append(i)
            except:
                pass
        if self.debug:
            print(f"Found {len(self.servos)} Servos: {self.servos}")

        return self.servos

    def getBatteryVoltage(self):
        tries = 0

        # it sometimes takes a second or two for the xArm to respond immediately after connecting
        while tries < 5:
            self._send(self.CMD_GET_BATTERY_VOLTAGE)

            data = self._recv(self.CMD_GET_BATTERY_VOLTAGE)
            if not data:
                tries += 1
                time.sleep(1)
                continue

            return (data[1] * 256 + data[0]) / 1000.0

        # we tried for 5 seconds to no avail
        return 0.0

    def _send(self, cmd, data=None):
        if data is None:
            data = []
        if self.debug:
            print(f'Tx Command {"0x{:02x}".format(cmd)} (Length ' + str(len(data)) + '): ' + ' '.join('0x{:02x}'.format(x) for x in data))

        if self._is_serial:
            self._device.flush()
            self._device.write([self.SIGNATURE, self.SIGNATURE, len(data) + 2, cmd])
            if len(data) > 0:
                self._device.write(data)
        else:  # Is USB
            report_data = [
                0, 
                self.SIGNATURE, 
                self.SIGNATURE, 
                len(data) + 2,
                cmd
            ]
            if len(data):
                report_data.extend(data)
            self._usb_recv_event = False
            self._device.write(report_data)

    def _recv(self, cmd):
        if self._is_serial:
            data = self._device.read(4)

            if self.debug:
                print(f'Rx Command {"0x{:02x}".format(cmd)} (Length ' + str(len(data)) + '): ' + ' '.join('0x{:02x}'.format(x) for x in data))

            if data[0] == self.SIGNATURE and data[1] == self.SIGNATURE and data[3] == cmd:
                length = data[2]
                data = self._device.read(length)
                return data
            else:
                return None
        else:  # Is USB
            self._input_report = self._device.read(64, 50)
            if len(self._input_report) < 4:
                # the minimum frame size is 4 (SIGNATURE, SIGNATURE, LENGTH, CMD)
                if self.debug:
                    print(f'Did not receive a response for the command {"0x{:02x}".format(cmd)}')
                return None
            if self._input_report[0] == self.SIGNATURE and \
                    self._input_report[1] == self.SIGNATURE and \
                    self._input_report[3] == cmd:
                length = self._input_report[2]
                data = self._input_report[4:4 + length]
                if self.debug:
                    print(f'Rx Command {"0x{:02x}".format(cmd)} (Length ' + str(len(data)) + '): ' + ' '.join(
                        '0x{:02x}'.format(x) for x in data))
                return data
            return None
