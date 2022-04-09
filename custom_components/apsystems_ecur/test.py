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
import APSystemsECUR

if len(sys.argv) > 1:
    ip_address=sys.argv[1]
else:
    print('Please provide ip-address as second argument: python3 test.py 192.168.1.2')
    raise Exception ('Invalid argument')

print('===HTTP test ===')
ecu_HTTP=APSystemsECUR.APSystemsECUR (ip_address, 80)
print('SYNC Query')
r=ecu_HTTP.query_ecu()
print(r)
print('Async Query')
r=asyncio.run( ecu_HTTP.async_query_ecu () )
print(r)

print('===TCP test ===')
ecu_TCP=APSystemsECUR.APSystemsECUR (ip_address)
print('SYNC Query')
r=ecu_TCP.query_ecu()
print(r)
print('Async Query')
r=asyncio.run( ecu_TCP.async_query_ecu () )
print(r)
print('=== test done ===')
