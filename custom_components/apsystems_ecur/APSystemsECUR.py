#!/usr/bin/env python3

import asyncio
from re import T
import socket
import binascii
import json
import logging
from bs4 import BeautifulSoup
import time
import aiohttp
import numpy

_LOGGER = logging.getLogger(__name__)

from pprint import pprint

class APSystemsInvalidData(Exception):
    pass

class APSystemsECUR:

    def __init__(self, ipaddr, port=8899, raw_ecu=None, raw_inverter=None):
        self.ipaddr = ipaddr
        self.port = port

        #http_query variables...
        self.url_prefix= "http://" + ipaddr + "/index.php"
        self.url_old_power_graph = self.url_prefix + "/realtimedata/old_power_graph"
        self.url_old_energy_graph = self.url_prefix + "/realtimedata/old_energy_graph"
        self.url_realtimedata= self.url_prefix + "/realtimedata"
        self.url_wlan = self.url_prefix + "/management/wlan" 
        self.grid = {}
        self.inverters = {}
        self.timestamp = "" #string formatted date
        self.ts = None #time object
        self.ts_ymd = "" #string formatted date
        self.ecu_last_query_date  = "1970-01-01" #string formatted date
        self.ecu_id = "" #static. unique ECU id
        
        self.qty_of_inverters = 0  #static
        self.inverter_qty_online = 0
        self.lifetime_energy = 0 #kwh
        self.current_power = 0 #W
        self.peak_power = 0 #W
        self.median_power = 0 #kwh
        self.median_power = 0 #kwh
        self.today_energy = 0 #kwh
        self.week_mean_power = 0 #kwh
        self.week_median_power = 0 #kwh
        self.week_mean_power = 0 #kwh
        self.page = None # for debugging puposes


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
        self.firmware = "" 
        self.timezone = ""

        self.vsl = 0
        self.tsl = 0

        self.ecu_raw_data = raw_ecu
        self.inverter_raw_data = raw_inverter
        self.inverter_raw_signal = None

        self.read_buffer = b''

        self.reader = None
        self.writer = None

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
    
    def query_ecu(self):

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.ipaddr,self.port))

        sock.sendall(self.ecu_query.encode('utf-8'))
        self.ecu_raw_data = sock.recv(self.recv_size)

        self.process_ecu_data()

        cmd = self.inverter_query_prefix + self.ecu_id + self.inverter_query_suffix
        sock.sendall(cmd.encode('utf-8'))
        self.inverter_raw_data = sock.recv(self.recv_size)

        cmd = self.inverter_signal_prefix + self.ecu_id + self.inverter_signal_suffix
        sock.sendall(cmd.encode('utf-8'))
        self.inverter_raw_signal = sock.recv(self.recv_size)

        sock.shutdown(socket.SHUT_RDWR)
        sock.close()

        data = self.process_inverter_data()

        data["ecu_id"] = self.ecu_id
        data["today_energy"] = self.today_energy
        data["lifetime_energy"] = self.lifetime_energy
        data["current_power"] = self.current_power


        return(data)

    #http IO
    async def getHTTPData(self, url ,data):

        async with aiohttp.ClientSession() as session:
            try:
                headers = {'content-type': 'text/html; charset=UTF-8'}
                async with session.post(url, data = data,headers =headers) as resp:
                    response=await resp.text()
                    if resp.status not in [200]:
                        raise Exception ('Error accessing url %s . HTTP status code %d' %(url,resp.status) )
            except:
                raise
            finally:
                await session.close()
        return response, resp

    async def http_query_ecu(self):

        self.grid = {}
        self.ts=time.time() #epoch is sec
        self.ts_ymd=time.strftime('%Y-%m-%d',time.localtime(self.ts))

        #get ecu basics (like ecu_id). @startup and each day
        if  not self.ecu_last_query_date == self.ts_ymd:
            #get all basic data like converter/firmware etc via TCP
            result = await self.async_query_ecu()
            #HTTP version. Can collect only ecu_id for now. When possible should replace TCP
            await self.getBasicStats()
            _LOGGER.info('Queried basic info on %s: firmware=%s ecu_id=%s' %(self.ts_ymd, self.firmware, self.ecu_id) )

        #get 5 minute updates
        await self.getDailyStats()

        #get weekly stats (once per day)
        if not self.ecu_last_query_date == self.ts_ymd:
            await self.getWeeklyStats()

        #build response
        self.grid['timestamp'] = self.timestamp
        self.grid['inverter_qty'] = self.qty_of_inverters
        self.grid['inverter_qty_online'] = self.inverter_qty_online
        self.grid['inverters'] = self.inverters

        self.grid["ecu_id"] = self.ecu_id
        self.grid["firmware"] = self.firmware
        self.grid["today_energy"] = self.today_energy
        self.grid["peak_power"] = self.peak_power
        self.grid["median_power"] = self.median_power
        self.grid["mean_power"] = self.mean_power
        self.grid["week_peak_power"] = self.week_peak_power
        self.grid["week_median_power"] = self.week_median_power
        self.grid["week_mean_power"] = self.week_mean_power
        self.grid["lifetime_energy"] = self.lifetime_energy
        self.grid["current_power"] = self.current_power
 
        return self.grid

    async def getBasicStats(self):
        #get ecu_id (via wlan page)
        response , resp= await self.getHTTPData(self.url_wlan, '')
        soup = BeautifulSoup(response,features="html.parser")
        TAG = soup.findAll('input',attrs={'name':'SSID'})
        if TAG is None or len(TAG) == 0:
            _LOGGER.warning(f"Failed to get basic data from query on {self.url_wlan}")
        else:
            VALUE_list = TAG[0].attrs['value'].split('_')
            if VALUE_list[0] == 'ECU':
                self.ecu_id = TAG[0].attrs['value'].split('_')[-1]

    async def getDailyStats(self):
        #get daily production from webAPI
        postdata='date=' + self.ts_ymd #query today. resp=headers, response=content
        response , resp= await self.getHTTPData(self.url_old_power_graph, postdata)

        #parse page result
        rdict=json.loads(response) #convert response to dictionary
        if len(rdict['power']) == 0: #queried too early. No data yet for this date
            self.current_power = 0
            self.peak_power = 0
            last_time_update = 0
            self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) #use current time
            _LOGGER.warning(f"Querying ECU while not producing power.")
        else:
            last_time_update = int(rdict['power'][-1]['time']/1000) #last update (epoch in millisec)
            self.current_power = rdict['power'][-1]['each_system_power']

            power_list= [power['each_system_power'] for power in rdict['power']]
            self.peak_power = numpy.max(power_list)
            self.median_power = round(numpy.median(power_list)/1000,2)
            self.mean_power = round(numpy.mean(power_list)/1000,2)

            self.timestamp = time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(self.ts))
            if int(self.ts)-last_time_update > 360: #no new updates after 6 minute interval assume 0
                self.current_power = 0
            self.today_energy = float(rdict['today_energy'])
        
        #scrape inverter data from internal webpage
        response , resp= await self.getHTTPData(self.url_realtimedata, '')
        self.parseTable(response,'table table-condensed table-bordered')

    async def getWeeklyStats(self):
        #get daily production from webAPI
        postdata='period=weekly'
        response , resp= await self.getHTTPData(self.url_old_energy_graph, postdata)
        self.page = response
        rdict=json.loads(response)
        energy_list= [energy['energy'] for energy in rdict['energy']]
        self.week_peak_power = numpy.max(energy_list)
        self.week_median_power = round(numpy.median(energy_list),2)
        self.week_mean_power = round(numpy.mean(energy_list),2)
        self.ecu_last_query_date = self.ts_ymd

    def parseTable(self,page,tableID):

        self.inverters={}
        current_inverter_id=0
        self.inverter_qty_online=0
        soup = BeautifulSoup(page, 'html.parser')
        table = soup.find('table', class_=tableID)
        #<th scope="col">Inverter ID</th>
        #<th scope="col">Current Power</th>
        #<th scope="col">DC Voltage</th>
        #<th scope="col">Grid Frequency</th>
        #<th scope="col">Grid Voltage</th>
        #<th scope="col">Temperature</th>
        #<th scope="col">Reporting Time</th>
        for row in table.tbody.find_all('tr'):    
        # Find all data for each column
            columns = row.find_all('td')
            num_col=len(columns)
            if (columns != []):
                inverter_id,channel_id = columns[0].text.strip().split('-')
                if num_col == 7:
                    self.timestamp= columns[6].text.strip()
                    if inverter_id != current_inverter_id:
                        current_inverter_id = inverter_id
                        power=[]
                        dc_voltage=[]
                        grid_voltage=[]
                        channels=[]
                        self.inverters[inverter_id] = ({'uid' :inverter_id })
                        if columns[3].text.strip() == '-': #inverter offline (no power generated)
                            self.inverters[inverter_id].update({'online' : False})
                            self.inverters[inverter_id].update({'frequency' : 0.0})
                            self.inverters[inverter_id].update({'temperature' : -100}) #from tcp results when offline
                        else:
                            self.inverter_qty_online+=1
                            self.inverters[inverter_id].update({'online' : True})
                            self.inverters[inverter_id].update({'frequency' : float(columns[3].text.strip().split(' ')[0])} )
                            self.inverters[inverter_id].update({'temperature' :int(columns[5].text.strip().split(' ')[0])} )
                            gvolt=columns[4].text.strip()
                            if len(gvolt) > 5: grid_voltage.append(int(gvolt.split(' ')[1])) #grid voltage (1 or 3 phase)
                else:
                    gvolt=columns[3].text.strip()
                    if len(gvolt) > 5: grid_voltage.append(int(gvolt.split(' ')[1])) #grid voltage (1 or 3 phase)
                if self.inverters[inverter_id]['online']:
                    power.append(int(columns[1].text.strip().split(' ')[0])) #current_power per channel
                    dc_voltage.append(int(columns[2].text.strip().split(' ')[0])) #dc voltage per channe
                else:
                    power.append(0)
                    dc_voltage.append(0)
                    grid_voltage.append(0)
                channels.append(channel_id)
                self.inverters[inverter_id].update({'model' : 'unknown' }) #not known on internal website
                self.inverters[inverter_id].update({'signal' : 0 }) #not known on internal website
                self.inverters[inverter_id].update({'channel_qty' : len(channels)})
                self.inverters[inverter_id].update({'power' : power}) #total=current_power
                self.inverters[inverter_id].update({'voltage' : grid_voltage})
                self.inverters[inverter_id].update({'dc_voltage' : dc_voltage})
                #self.inverters[inverter_id].update({'channels' : channels}) 

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


