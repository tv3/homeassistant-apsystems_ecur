#!/usr/bin/env python3

import asyncio
import socket
import binascii
import logging

_LOGGER = logging.getLogger(__name__)

class APSystemsInvalidData(Exception):
    pass

class APSystemsTCP:

    def __init__(self, ipaddr, port=8899, raw_ecu=None, raw_inverter=None):
        self.ipaddr = ipaddr
        self.port = port

        self.ecu_id = None #static
        self.qty_of_inverters = 0  #static
        self.inverter_qty_online = 0
        self.lifetime_energy = 0 #kwh
        self.current_power = 0 #W
        self.today_energy = 0 #kwh 

        # what do we expect socket data to end in
        self.recv_suffix = b'END\n'

        # how long to wait on socket commands until we get our recv_suffix
        self.timeout = 5

        # how many times do we try the same command in a single update before failing
        self.cmd_attempts = 3

        # how big of a buffer to read at a time from the socket
        self.recv_size = 4096

        self.qs1_ids = [ "802", "801", "804", "806" ]
        self.yc600_ids = [ "406", "407", "408", "409" ]
        self.yc1000_ids = [ "501", "502", "503", "504" ]
        self.ds3_ids = [ "703", "704" ]

        self.cmd_suffix = "END\n"
        self.ecu_query = "APS1100160001" + self.cmd_suffix
        self.inverter_query_prefix = "APS1100280002"
        self.inverter_query_suffix = self.cmd_suffix

        self.inverter_signal_prefix = "APS1100280030"
        self.inverter_signal_suffix = self.cmd_suffix

        self.inverter_byte_start = 26

        self.qty_of_online_inverters = 0
        self.last_update = None
        self.firmware = None
        self.timezone = None

        self.vsl = 0
        self.tsl = 0

        self.ecu_raw_data = raw_ecu
        self.inverter_raw_data = raw_inverter
        self.inverter_raw_signal = None

        self.read_buffer = b''

        self.reader = None
        self.writer = None

#
# TCO/Socket IO
#

## SYNC IO
    def close_socket(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            self.socket_open = False
        except:
            pass

    def open_socket(self):
        _LOGGER.debug(f"Open socket to ECU on {self.ipaddr} {self.port}")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.ipaddr, self.port))
        self.socket_open = True
    
    def read_from_socket(self):
        self.read_buffer = b''
        end_data = None

        while end_data != self.recv_suffix:
            data = self.sock.recv(self.recv_size)
            if data == b'':
                break
            self.read_buffer += data
            size = len(self.read_buffer)
            end_data = self.read_buffer[size-4:]

        return self.read_buffer

# open>send>read>close
    def reqTCPData(self, cmd):
        _LOGGER.debug(f"Request data from socket for command: {cmd} ")
        try:
            self.open_socket()
            self.sock.sendall(cmd.encode('utf-8'))
            response = self.read_from_socket()
            _LOGGER.debug(f"Received data from socket")
            return response
        except:
            msg = "IO Error after querying for ECU data cmd={cmd.rstrip()}. (timeout={self.timeout}s) "
            self.add_error(msg)
            raise
        finally:
            self.close_socket()


## ASYNC IO
    async def async_read_from_socket(self):
        self.read_buffer = b''
        end_data = None

        while end_data != self.recv_suffix:
            data = await self.reader.read(self.recv_size)
            if data == b'':
                break
            self.read_buffer += data
            size = len(self.read_buffer)
            end_data = self.read_buffer[size-4:]

        return self.read_buffer

    async def async_send_read_from_socket(self, cmd):
        current_attempt = 0
        while current_attempt < self.cmd_attempts:
            current_attempt += 1

            self.writer.write(cmd.encode('utf-8'))
            await self.writer.drain()

            try:
                return await asyncio.wait_for(self.async_read_from_socket(), 
                    timeout=self.timeout)
            except Exception as err:
                pass

        self.writer.close()
        await self.writer.wait_closed()

        raise APSystemsInvalidData(f"Incomplete data from ECU after {current_attempt} attempts, cmd='{cmd.rstrip()}' data={self.read_buffer}")

    async def async_query_ecu(self):
        self.reader, self.writer = await asyncio.open_connection(self.ipaddr, self.port)
        _LOGGER.info(f"Connected to {self.ipaddr} {self.port}")

        cmd = self.ecu_query
        self.ecu_raw_data = await self.async_send_read_from_socket(cmd)

        self.process_ecu_data()

        if self.lifetime_energy == 0:
            self.writer.close()
            await self.writer.wait_closed()

            raise APSystemsInvalidData(f"ECU returned 0 for lifetime energy, raw data={self.ecu_raw_data}")

        if "ECU_R_PRO" in self.firmware or "ECU-C" in self.firmware:
            self.writer.close()
            await self.writer.wait_closed()

            # sleep 1 seconds before re-opening the socket
            await asyncio.sleep(1)

            _LOGGER.info(f"Re-connecting to ECU_R_PRO on {self.ipaddr} {self.port}")
            self.reader, self.writer = await asyncio.open_connection(self.ipaddr, self.port)

        cmd = self.inverter_query_prefix + self.ecu_id + self.inverter_query_suffix
        self.inverter_raw_data = await self.async_send_read_from_socket(cmd)


        if "ECU_R_PRO" in self.firmware or "ECU-C" in self.firmware:
            self.writer.close()
            await self.writer.wait_closed()

            # sleep 1 seconds before re-opening the socket
            await asyncio.sleep(1)

            _LOGGER.info(f"Re-connecting to ECU_R_PRO on {self.ipaddr} {self.port}")
            self.reader, self.writer = await asyncio.open_connection(self.ipaddr, self.port)

        cmd = self.inverter_signal_prefix + self.ecu_id + self.inverter_signal_suffix
        self.inverter_raw_signal = await self.async_send_read_from_socket(cmd)

        self.writer.close()
        await self.writer.wait_closed()


        data = self.process_inverter_data()
        data["ecu_id"] = self.ecu_id
        data["today_energy"] = self.today_energy
        data["lifetime_energy"] = self.lifetime_energy
        data["current_power"] = self.current_power


        return(data)

    def sync_query_ecu(self):
        return self.query_ecu()

    def query_ecu(self):

        cmd = self.ecu_query
        self.ecu_raw_data = self.reqTCPData(cmd)
        self.process_ecu_data()

        cmd = self.inverter_query_prefix + self.ecu_id + self.inverter_query_suffix
        self.inverter_raw_data = self.reqTCPData(cmd)

        cmd = self.inverter_signal_prefix + self.ecu_id + self.inverter_signal_suffix
        self.inverter_raw_signal = self.reqTCPData(cmd)

        data = self.process_inverter_data()

        data["ecu_id"] = self.ecu_id
        data["today_energy"] = self.today_energy
        data["lifetime_energy"] = self.lifetime_energy
        data["current_power"] = self.current_power

        return(data)


    def aps_int(self, codec, start):
        try:
            return int(binascii.b2a_hex(codec[(start):(start+2)]), 16)
        except ValueError as err:
            debugdata = binascii.b2a_hex(codec)
            raise APSystemsInvalidData(f"Unable to convert binary to int location={start} data={debugdata}")
 
    def aps_short(self, codec, start):
        try:
            return int(binascii.b2a_hex(codec[(start):(start+1)]), 8)
        except ValueError as err:
            debugdata = binascii.b2a_hex(codec)
            raise APSystemsInvalidData(f"Unable to convert binary to short int location={start} data={debugdata}")

    def aps_double(self, codec, start):
        try:
            return int (binascii.b2a_hex(codec[(start):(start+4)]), 16)
        except ValueError as err:
            debugdata = binascii.b2a_hex(codec)
            raise APSystemsInvalidData(f"Unable to convert binary to double location={start} data={debugdata}")
    
    def aps_bool(self, codec, start):
        return bool(binascii.b2a_hex(codec[(start):(start+2)]))
    
    def aps_uid(self, codec, start):
        return str(binascii.b2a_hex(codec[(start):(start+12)]))[2:14]
    
    def aps_str(self, codec, start, amount):
        return str(codec[start:(start+amount)])[2:(amount+2)]
    
    def aps_timestamp(self, codec, start, amount):
        timestr=str(binascii.b2a_hex(codec[start:(start+amount)]))[2:(amount+2)]
        return timestr[0:4]+"-"+timestr[4:6]+"-"+timestr[6:8]+" "+timestr[8:10]+":"+timestr[10:12]+":"+timestr[12:14]

    def check_ecu_checksum(self, data, cmd):
        datalen = len(data) - 1
        try:
            checksum = int(data[5:9])
        except ValueError as err:
            debugdata = binascii.b2a_hex(data)
            raise APSystemsInvalidData(f"Error getting checksum int from '{cmd}' data={debugdata}")

        if datalen != checksum:
            debugdata = binascii.b2a_hex(data)
            raise APSystemsInvalidData(f"Checksum on '{cmd}' failed checksum={checksum} datalen={datalen} data={debugdata}")

        start_str = self.aps_str(data, 0, 3)
        end_str = self.aps_str(data, len(data) - 4, 3)

        if start_str != 'APS':
            debugdata = binascii.b2a_hex(data)
            raise APSystemsInvalidData(f"Result on '{cmd}' incorrect start signature '{start_str}' != APS data={debugdata}")

        if end_str != 'END':
            debugdata = binascii.b2a_hex(data)
            raise APSystemsInvalidData(f"Result on '{cmd}' incorrect end signature '{end_str}' != END data={debugdata}")

        return True

    def process_ecu_data(self, data=None):
        if not data:
            data = self.ecu_raw_data

        self.check_ecu_checksum(data, "ECU Query")

        self.ecu_id = self.aps_str(data, 13, 12)
        self.qty_of_inverters = self.aps_int(data, 46)
        self.qty_of_online_inverters = self.aps_int(data, 48)
        self.vsl = int(self.aps_str(data, 52, 3))
        self.firmware = self.aps_str(data, 55, self.vsl)
        self.tsl = int(self.aps_str(data, 55 + self.vsl, 3))
        self.timezone = self.aps_str(data, 58 + self.vsl, self.tsl)
        self.lifetime_energy = self.aps_double(data, 27) / 10
        self.today_energy = self.aps_double(data, 35) / 100
        self.current_power = self.aps_double(data, 31)

    def process_signal_data(self, data=None):
        signal_data = {}

        if not data:
            data = self.inverter_raw_signal

        self.check_ecu_checksum(data, "Signal Query")

        if not self.qty_of_inverters:
            return signal_data

        location = 15
        for i in range(0, self.qty_of_inverters):
            uid = self.aps_uid(data, location)
            location += 6

            strength = data[location]
            location += 1

            strength = int((strength / 255) * 100)
            signal_data[uid] = strength

        return signal_data

    def process_inverter_data(self, data=None):
        if not data:
            data = self.inverter_raw_data

        self.check_ecu_checksum(data, "Inverter data")

        output = {}

        timestamp = self.aps_timestamp(data, 19, 14)
        inverter_qty = self.aps_int(data, 17)

        self.last_update = timestamp
        output["timestamp"] = timestamp
        output["inverter_qty"] = inverter_qty
        output["inverters"] = {}

        # this is the start of the loop of inverters
        location = self.inverter_byte_start

        signal = self.process_signal_data()

        inverters = {}
        for i in range(0, inverter_qty):

            inv={}

            inverter_uid = self.aps_uid(data, location)
            inv["uid"] = inverter_uid
            location += 6

            inv["online"] = self.aps_bool(data, location)
            location += 1

            inv["unknown"] = self.aps_str(data, location, 2)
            location += 2

            inv["frequency"] = self.aps_int(data, location) / 10
            location += 2

            inv["temperature"] = self.aps_int(data, location) - 100
            location += 2

            inv["signal"] = signal.get(inverter_uid, 0)

            # the first 3 digits determine the type of inverter
            inverter_type = inverter_uid[0:3]
            if inverter_type in self.yc600_ids:
                (channel_data, location) = self.process_yc600(data, location)
                inv.update(channel_data)    

            elif inverter_type in self.qs1_ids:
                (channel_data, location) = self.process_qs1(data, location)
                inv.update(channel_data)
            
            elif inverter_type in self.yc1000_ids:
                (channel_data, location) = self.process_yc1000(data, location)
                inv.update(channel_data)
                
            elif inverter_type in self.ds3_ids:
                (channel_data, location) = self.process_ds3(data, location)
                inv.update(channel_data)    

            else:
                raise APSystemsInvalidData(f"Unsupported inverter type {inverter_type}")

            inverters[inverter_uid] = inv

        output["inverters"] = inverters
        return (output)
    
    def process_yc1000(self, data, location):

        power = []
        voltages = []

        power.append(self.aps_int(data, location))
        location += 2

        voltages.append(self.aps_int(data, location))
        location += 2

        power.append(self.aps_int(data, location))
        location += 2
        
        voltages.append(self.aps_int(data, location))
        location += 2

        power.append(self.aps_int(data, location))
        location += 2
        
        voltages.append(self.aps_int(data, location))
        location += 2

        power.append(self.aps_int(data, location))
        location += 2

        output = {
            "model" : "YC1000",
            "channel_qty" : 4,
            "power" : power,
            "voltage" : voltages
        }

        return (output, location)

    
    def process_qs1(self, data, location):

        power = []
        voltages = []

        power.append(self.aps_int(data, location))
        location += 2

        voltage = self.aps_int(data, location)
        location += 2

        power.append(self.aps_int(data, location))
        location += 2

        power.append(self.aps_int(data, location))
        location += 2

        power.append(self.aps_int(data, location))
        location += 2

        voltages.append(voltage)

        output = {
            "model" : "QS1",
            "channel_qty" : 4,
            "power" : power,
            "voltage" : voltages
        }

        return (output, location)


    def process_yc600(self, data, location):
        power = []
        voltages = []

        for i in range(0, 2):
            power.append(self.aps_int(data, location))
            location += 2

            voltages.append(self.aps_int(data, location))
            location += 2

        output = {
            "model" : "YC600",
            "channel_qty" : 2,
            "power" : power,
            "voltage" : voltages,
        }

        return (output, location)
    
    def process_ds3(self, data, location):
        power = []
        voltages = []

        for i in range(0, 2):
            power.append(self.aps_int(data, location))
            location += 2

            voltages.append(self.aps_int(data, location))
            location += 2

        output = {
            "model" : "DS3",
            "channel_qty" : 2,
            "power" : power,
            "voltage" : voltages,
        }

        return (output, location)


