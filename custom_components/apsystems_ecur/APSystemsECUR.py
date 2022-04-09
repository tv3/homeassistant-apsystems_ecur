#!/usr/bin/env python3

import logging

_LOGGER = logging.getLogger(__name__)

#
# split TCP/HTTP into separate modules
# This module is used as abstraction of the TCP/HTTP modules, so HA integration points don't change
#

import APSystemsHTTP as EHTTP
import APSystemsTCP as ETCP

class APSystemsECUR:

    def __init__(self, ipaddr, port=8899):
        self.ipaddr = ipaddr
        self.port = port

        if port == 80:
            _LOGGER.info('Setting up HTTP integration.')
            self.ECU=EHTTP.APSystemsHTTP(ipaddr,port)
        else:
            _LOGGER.info('Setting up TCP integration based on port number %d' %(port))
            self.ECU=ETCP.APSystemsTCP(ipaddr,port)

    async def async_query_ecu(self):
        data=await self.ECU.async_query_ecu()
        return(data)
    
    def query_ecu(self):
        data=self.ECU.sync_query_ecu()
        return(data)