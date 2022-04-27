#!/usr/bin/env python3

#
# To run test (example)
# python3 test.py 192.168.1.2
# TCP output is different from HTTP output. sync/async should be the same
# Tested on Mac
#
import asyncio
import sys
from ipaddress import ip_address


class test:

    def __init__(self, ip_address = '192.168.4.6') -> None:
        from APSystemsECUR import APSystemsECUR
        self.ip_address = ip_address
        self.ecu_HTTP=APSystemsECUR (ip_address, 80)
        self.ecu_TCP=APSystemsECUR (ip_address,8899)

    def do(self):
        print('===HTTP test ===')
        print('SYNC Query')
        #r=self.ecu_HTTP.query_ecu()
        #print(r)
        print('Async Query')
        r=asyncio.run( self.ecu_HTTP.query_ecu () )
        print(r)

        print('===TCP test ===')
        print('SYNC Query')
        #r = self.ecu_TCP.query_ecu()
        #print(r)
        print('Async Query')
        r = asyncio.run( self.ecu_TCP.query_ecu () )
        print(r)
        print('=== test done ===')
#
# MAIN
#
if (__name__ == '__main__'):
    if len(sys.argv) > 1:
        a=test(sys.argv[1])
        a.do()
    else:
        print('Supply ip-address for test')
