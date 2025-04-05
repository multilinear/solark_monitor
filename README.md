# solark_monitor
DEPRECATED:
This has been replaced by https://codeberg.org/multilinear/solark_monitor
which has far better error handling, is more stable, and more efficient, due in
large part to being written in rust. The python version is left here though as a
potentially useful basis for others wanting to do something similar in python.

Poles a solark power inverter over modbus and places results in influxDB, while also sending alerts on interesting conditions to matrix.

This script is intended to run on a machine proximal to your solark connected to it via a cable. It poles the solark over modbus, gathers the requested metrics. You can write "alerts" where if the lambda evaluates to true a message will be sent to matrix. The metrics are also dumped into influxDB.

: This is basically deprecated in favor of



## Installation/dependencies
It's really just this script, keep these two in the same directory so one can import the other. You'll need to find the dependencies.
You'll need: 
- pymodbus
- influxdb_client
- matrix-nio

This was developed with python 3.13, pymodbus-3.6.8, influxdb-client-1.24.0, and matrix-nio-0.24.0

## Configuration

All configuration is done in `solark_monitor_config.py`

For a definition of the metrics that can be gathered see: [[https://www.dth.net/solar/sol-ark/Modbus%20Sol-Ark%20V1.1%28Public%20Release%29.pdf]]
`Registers` in `solark_monitor_config.py` defines what data we pull.

## Testing:

I have a Solark-15K-2P-N, so that is what I'm testing with. I'm running this service on a small Gentoo x86_64 machine. I have a linux-compatible RS-232 USB adapter for which I have support in my kernel. This is connected to the external RS-232 port in place of the wireless uplink. I understand it's possible to use the RS-485 link that is inside the box, but from reading about this I believe there are potentially some complications if already using this for the batteries.

## Design choices:

My goal was to actually get something usable for myself, and clean *enough* that I could trust it. It could definitely be improved, but it's "good enough" that I'm actively using it. I attempted using a several different APIs for matrix, and a couple of different modbus clients. I started asynchronous, then went synchronous, got it working, then went back to asynchronous. The main reason I'm using asynchronous is that the best matrix APIs I found are async so simply making everything async keeps things simple. 

## Thanks:

I developed this entirely on my own, but hard work was already done by others to understand the details of using solark modbus, and I learned a lot from online discussion threads on the topic. Maybe I'll flesh this out with more details of who I got ideas from someday.

## Implied warrenty etc:

There is NO implied warrenty or fitness for use! If you break your god-awful expensive inverter it's not my fault. I just wrote some code I'm using and am sharing it to help others. This is the "read only" modbus API so it shouldn't break anything, but "shouldn't" is never the same as "can't". So good luck.
