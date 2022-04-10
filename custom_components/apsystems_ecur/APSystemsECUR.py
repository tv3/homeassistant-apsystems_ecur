#!/usr/bin/env python3

import logging

_LOGGER = logging.getLogger(__name__)

#
# split TCP/HTTP into separate modules
# This module is used as abstraction of the TCP/HTTP modules, so HA integration points don't change
#

#import APSystemsHTTP as EHTTP
#import APSystemsTCP as ETCP

from .APSystemsHTTP import APSystemsHTTP
from .APSystemsTCP import APSystemsTCP

class APSystemsInvalidData(Exception):
    pass

class APSystemsECUR:

    def __init__(self, ipaddr, port=80): #port=8899 < TCP
        self.ipaddr = ipaddr
        self.port = port

        if port == 80:
            _LOGGER.info('Setting up HTTP integration.')
            self.ECU=APSystemsHTTP(ipaddr,port)
        else:
            _LOGGER.info('Setting up TCP integration based on port number %d' %(port))
            self.ECU=APSystemsTCP(ipaddr,port)
    
    def query_ecu(self):
        data=self.ECU.sync_query_ecu()
        return(data)