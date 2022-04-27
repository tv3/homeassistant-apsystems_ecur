#!/usr/bin/env python3

import logging
import asyncio

_LOGGER = logging.getLogger(__name__)

#
# split TCP/HTTP into separate modules
# This module is used as abstraction of the TCP/HTTP modules, so HA integration points don't change
#

from APSystemsHTTP import APSystemsHTTP
from APSystemsTCP import APSystemsTCP

class APSystemsInvalidData(Exception):
    pass

class APSystemsECUR:
        

    def __init__(self, ipaddr, port=80):
        self.ipaddr = ipaddr
        self.port = port
        #Variables referenced by __init__.py
        self.firmware = None
        self.timezone = None
        self.ecu_id = None

        if port == 80:
            _LOGGER.info('Setting up HTTP integration.')
            self.ECU=APSystemsHTTP(ipaddr,port)
        else:
            _LOGGER.info('Setting up TCP integration based on port number %d' %(port))
            self.ECU=APSystemsTCP(ipaddr,port)
    
    async def query_ecu(self):
        data= await self.ECU.async_query_ecu()
        self.ecu_id=data.get('ecu_id')
        print(self.ecu_id)
        self.ecu_id=data.get('firmware')
        self.ecu_id=data.get('timezone')
        return(data)