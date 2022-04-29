# Home-Assistant APSystems ECU-R and ECU-C (?) Integration
This is a custom component for [Home-Assistant](http://home-assistant.io) that adds support for the [APsystems](http://www.apsystems.com) ECU-R and ECU-C (not B!) solar Energy Communication Unit. With this component you are able to monitor your PV installation (inverters) in detail.

**This version is specific for the ECU with ECU-R-PRO firmware as it has an internal website that can be queried. This has proven to be a stable way of getting data from the ECU.
**

## Background & acknowledgement
This integration queries the local ECU every 5 minutes for new data. This was done without a public API, and by listening to and interpreting the protocol the APSystems ECU phone app (ECUapp) uses when setting up the PV array.

This couldn't have been done without the hardwork of @checking12 and @HAEdwin on the home assistant forum, and all the other people from this forum (https://gathering.tweakers.net/forum/list_messages/2032302/1)

## Prerequisites
You own an APSystems ECU-R or ECU-C (not ECU-B) and any combination of YC600, YC1000 or QS1/QS1A inverter.
## Release notes

### v1.1.2.1
HTTP version combined with TCP for getting additional info

TODO: many things... 
- add inverter model details from TCP query to HTTP query output
- update TCP socket IO

### v1.1.2
Make ECU-C devices behave like ECU_R_PRO devices and close the socket down between each query.  Add support for new ds3 inverter type 704

### v1.1.1
Added support to setup the integration in the new config flow GUI.  Fixed a caching issue when the ECU is down on startup leading to creation of sensor entries.  Once you install this update all configuration is done via the GUI.

### Old release notes
```
v1.0.0 First release
v1.0.1 Revised the readme, added support for YC1000 and added versioning to the manifest
v1.0.2 Added support for QS1A
v1.0.3 Added support for 2021.8.0 (including energy panel), fixed some issues with ECU_R_PRO
v1.0.4 Added optional scan_interval to config
v1.0.5 Fixed energy dashboard and added HACS setup option description in readme.md
v1.0.6 Replaces deprecated device_state_attributes, added ECU-B compatibility
2022.1.0 Improved configuration notes, applied CalVer, cleanup code, improvements on ECU data
2022.1.0 - [update] Attempt to fix issues with ECU_R_PRO, detect 0 from lifetime energy to prevent issues in energy dashboard
v1.0.7 - provide stateclass for current_power and today_energy and start git tagging version number
v1.0.8 - fix HA version in hacs.json file
```

## Setup
Option 1:
Easiest option, install the custom component using HACS by searching for "APSystems ECU-R". If you are unable to find the integration in HACS, select HACS in left pane, select Integrations. In the top pane right from the word Integrations you can find the menu (three dots above eachother). Select Custom Repositories and add the URL: https://github.com/ksheumaker/homeassistant-apsystems_ecur below that select category Integration.

Option 2:
Copy contents of the apsystems_ecur/ directory into your <HA-CONFIG>/custom_components/apsystems_ecur directory (```/config/custom_components``` on hassio)
Your directory structure should look like this:
```
   config/custom_components/apsystems_ecur/__init__.py
   config/custom_components/apsystems_ecur/APSystemsECUR.py
   config/custom_components/apsystems_ecur/binary_sensor.py
   config/custom_components/apsystems_ecur/const.py
   config/custom_components/apsystems_ecur/manifest.json
   config/custom_components/apsystems_ecur/sensor.py
   config/custom_components/apsystems_ecur/services.yaml
   ....
```

## Configuration

Go to the integrations screen and choose "Add Integration" search for APSystemsECU-R and provide the WIFI IP address, and update interval (60 seconds is the default).

_Warning_ the ECU device isn't the most powerful querying it more frequently could lead to stability issues with the ECU and require a power cycle.

Although you can query the ECU 24/7, it is an option to stop the query after sunset (apsystems_ecur.stop_query) and only start the query again at sunrise (apsystems_ecur.start_query). You can do this by adding automations. 

Reason for this are the maintenance tasks that take place on the ECU around 02.45-03.15 AM local time. During this period the ECU port is closed which results in error messages in the log if the integration tries to query for data. During maintenance, the ECU is checking whether all data to the EMA website has been updated, clearing cached data and the ECU is looking for software updates, updating the ECU firmware when applicable. Besides the log entries no harm is done if you query the ECU 24/7.

## Data available
The component supports getting data from the array as a whole as well as each individual invertor.

### Array Level Sensors

These sensors will show up under an `ECU [ID]` device, where [ID] is the unique ID of your ECU

* sensor.ecu_current_power - total amount of power (in W) being generated right now
* sensor.ecu_today_energy - total amount of energy (in kWh) generated today now. Use this sensor to populate the enrgy dashboard!!
* sensor.ecu_lifetime_energy - DO NOT USE. This sensor is NOT available with the http query function. Use ecu_today_energy! (total amount of energy (in kWh) generated from the lifetime of the array). It is only updated every day.

### Inverter Level Sensors

A new device will be created for each inverter called `Inverter [UID]` where [UID] is the unique ID of the Inverter

* sensor.inverter_[UID]_frequency - the AC power frequency in Hz
* sensor.inverter_[UID]_voltage - the AC voltage in V
* sensor.inverter_[UID]_temperature - the temperature of the invertor in your local unit (C or F)
* sensor.inverter_[UID]_signal - the signal strength of the zigbee connection
* sensor.inverter_[UID]_power_ch_[1-4] - the current power generation (in W) of each channel of the invertor - number of channels will depend on inverter model

## TODO
1. Code cleanup - it probably needs some work
2. Add online status of individual inverters
3. Improve ECU-R-PRO firmware compatibility
