#!/usr/bin/env python3

# Stripped version of APSystemsECUR.py. Removed TCP references. 
# Idea: have separate TCP/HTTP modules for querying
# Problem: needs multiple people as integration works differently with each model
# Current state: this stripped code could works as a replacement for APSystemsECUR.py, but is now just a separate file
# TODO: make this work independent of original changes in ksheumaker's repo.

import json
import logging
from bs4 import BeautifulSoup
import time
import requests
import numpy
import aiohttp
import asyncio

_LOGGER = logging.getLogger(__name__)

class APSystemsInvalidData(Exception):
    pass

class APSystemsHTTP:

    def __init__(self, ipaddr, port=80):
        self.ipaddr = ipaddr
        self.port = port

        #http_query variables...
        self.url_prefix= "http://" + ipaddr + ':' + str(self.port) + "/index.php"
        self.url_old_power_graph = self.url_prefix + "/realtimedata/old_power_graph"
        self.url_old_energy_graph = self.url_prefix + "/realtimedata/old_energy_graph"
        self.url_realtimedata= self.url_prefix + "/realtimedata"
        self.url_wlan = self.url_prefix + "/management/wlan" 

        self.AIO = False #do async IO?

        self.grid = {}
        self.ecu_last_query_date  = 0
        self.inverters = {}
        self.queried_static_info = False
        self.timestamp = 0
        self.ts = None
        self.ts_ymd = None
        self.ecu_id = None #static
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

        # how long to wait for IO
        self.timeout = 5

        self.qty_of_online_inverters = 0
        self.last_update = None
        self.firmware = None
        self.timezone = None

#
# HTTP IO
#

    #HTTP async IO
    async def asyncHTTP(self, url ,data):

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

    #HTTP sync IO
    def syncHTTP(self,url,data):
        try:
            headers = {'content-type': 'text/html; charset=UTF-8'}
            resp = requests.post(url, data=data, headers=headers, timeout=self.timeout)
            if not resp.ok:
                raise Exception ('Error accessing url %s . HTTP status code %d, %s' %(url,resp.status_code,resp.reason) )
        except:
            raise
        finally:
            resp.close()
        return resp.text, resp
#
# hide async from queries
#
    def reqHTTPData(self, url, data):
        if self.AIO:
            # encapsulate async task
            return asyncio.run(self.asyncHTTP(url, data) )
        else:
            return self.syncHTTP(url, data)

#
# query ECU
#

# interface async/sync
    async def async_query_ecu(self):
        self.AIO=True
        return self.do_query_ecu()

    def sync_query_ecu(self):
        self.AIO=False
        return self.do_query_ecu()

#
# process data
#
    def do_query_ecu(self):

        self.grid = {}
        self.ts=time.time() #epoch
        self.ts_ymd=time.strftime('%Y-%m-%d',time.localtime(self.ts))

        #get ecu basics (like ecu_id). Only after startup
        if self.queried_static_info == False or self.ecu_id is None: #first query
            self.getBasicStats()

        #get 5 minute updates
        self.getDailyStats()

        #get weekly stats (once per day)
        if not self.ecu_last_query_date == self.ts_ymd:
            self.getWeeklyStats()

        #build response
        self.grid['timestamp'] = self.timestamp
        self.grid['inverter_qty'] = self.qty_of_inverters
        self.grid['inverter_qty_online'] = self.inverter_qty_online
        self.grid['inverters'] = self.inverters

        self.grid["ecu_id"] = self.ecu_id
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

#
# get static data (queried at startup)
#
    def getBasicStats(self):
        #get ecu_id (via wlan page)
        response , resp = self.reqHTTPData(self.url_wlan, '')
        soup = BeautifulSoup(response, features="html.parser")
        TAG = soup.findAll('input',attrs={'name':'SSID'})
        if TAG is None or len(TAG) == 0:
            _LOGGER.warning(f"Failed to get basic data from query on {self.url_wlan}")
        else:
            VALUE_list = TAG[0].attrs['value'].split('_')
            if VALUE_list[0] == 'ECU':
                self.ecu_id = TAG[0].attrs['value'].split('_')[-1]
                self.queried_static_info = True

#
# get data for the day
#
    def getDailyStats(self):
        #get daily production from webAPI
        postdata='date=' + self.ts_ymd #query today. resp=headers, response=content
        response , resp = self.reqHTTPData(self.url_old_power_graph, postdata)

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
        response , resp = self.reqHTTPData(self.url_realtimedata, '')
        self.parseInverterTable(response,'table table-condensed table-bordered')

#
# get the week stats
#
    def getWeeklyStats(self):
        #get daily production from webAPI
        postdata='period=weekly'
        response , resp = self.reqHTTPData(self.url_old_energy_graph, postdata)
        self.page = response
        rdict=json.loads(response)
        energy_list= [energy['energy'] for energy in rdict['energy']]
        self.week_peak_power = numpy.max(energy_list)
        self.week_median_power = round(numpy.median(energy_list),2)
        self.week_mean_power = round(numpy.mean(energy_list),2)
        self.ecu_last_query_date = self.ts_ymd

#
# parse the inverter webpage (url_realtimedata).
#
    def parseInverterTable(self,page,tableID):

        self.inverters={}
        current_inverter_id=0
        self.inverter_qty_online=0
        soup = BeautifulSoup(page, 'html.parser')
        table = soup.find('table', class_=tableID)
        # THis is the general column makeup of webpage that we parse here
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
                self.qty_of_inverters = len(self.inverters) # set number of inverters
                #self.inverters[inverter_id].update({'channels' : channels}) 