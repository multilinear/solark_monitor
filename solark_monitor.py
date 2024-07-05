#!/usr/bin/python3

# runs on python 2.12
# As of this comment I'm using packages from gentoo package manager for
# my dependencies, here's the versions:
# - dev-python/pymodbus-3.6.8 from HomeAssistantRepository overlay

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder
import pymodbus
#from aioinflux import InfluxDBClient, InfluxDBWriteError
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import ASYNCHRONOUS
import time
import datetime
import logging
import subprocess
import nio # requires matrix-nio
import asyncio
import argparse
from solark_monitor_config import *

############ MATRIX STUFF ################

class Matrix: 
    # if this value is None that means we aren't connected
    _client = None
    _rooms = None
    _params = None

    """ True if connected, false otherwise """
    def __bool__(self) :
        if self._client:
            return True
        return False

    """ Connect with params from our last connection """
    async def reconnect(self):
        connect(self._params)

    """ Connect or reconnect """
    async def connect(self, params):
        self._params = params
        self._client = nio.AsyncClient(
                self._params['url'],
                self._params['user'])
        print(await self._client.login(self._params['passwd']))
        await self._client.sync()
        self._client.add_event_callback(self.invite_callback, nio.events.invite_events.InviteEvent)
        # Check that we're not broadcasting to anyone we shouldn't
        await self._query_rooms();
        if self._rooms is None:
            print('we are in no rooms? exiting')
            await self._client.close()
            return None
        print(f'in rooms: {self._rooms}')
        #users = await list_users(matrix_client, rooms)
        #if users is None or not is_allowed_users(users):
        #    print(f'extra users! users are {users} destroying client')
        #    await matrix_client.close()
        return self 

    """ Return the cached list if rooms """
    def get_rooms(): 
        return _rooms

    """ Send a message "msg" """
    async def send_msg(self, msg):
        for room in self._rooms:
            res = await self._client.room_send(
                room_id=room,
                message_type="m.room.message",
                content={"msgtype":"m.text", "body":msg}
            )
            if isinstance(res, nio.RoomSendError):
                print(f'Failed to send msg="{msg}" to room="{room}"')
                await self._client.close()    
                self._client = None
                return

    """ Updates the list of rooms, mostly for internal use """
    async def _query_rooms(self):
        rooms_response = await self._client.joined_rooms()
        if isinstance(rooms_response, nio.JoinedRoomsError):
            print(f'failed to query rooms error={rooms}')
            return None
        self._rooms = rooms_response.rooms
        return rooms_response.rooms

    """ Lists all users in the list of rooms supplied """
    async def list_users(rooms):
        members = set() 
        for room in rooms:
            res = await _client.joined_members(room)
            if isinstance(res, nio.JoinedMembersError):
                print(f'failed to list users in {room}, potential security problem') 
                return None
            members.update(set(i.user_id for i in res.members))
        return members

    """ Returns true if all users in the list are in the allowlist, false otherwise """
    def is_allowed_users(users):
        extra_users = users.difference(set(_params['allowlist'] + [_params['user']]))
        if extra_users:
            return False
        return True

    """ Callback called when someone invites us a to a room """ 
    async def invite_callback(self, room, event):
        print(f'callback called with room={room.room_id}, event={event}')
        user = event.sender
        if not is_allowed_users(set([user])):
            print(f'rejecting invite from {user}') 
            res = await self._client.room_leave(room.room_id)
            if isinstance(res, nio.RoomLeaveError):
                print(f'leave of {room} invited by {user} failed with error {res}')
                await self._client.close()
                self._client = None
                return
        print(f'accepting invite from {user}') 
        res = await self._client.join(room.room_id)
        if isinstance(res, nio.JoinError):
            print(f'Join of {room} invited by {user} failed with error {res}')
            await self._client.close()
            self._client = None
        _rooms.append(room.room_id)


############## SOLARK MODBUS STUFF ######################33

class Solark:
    _client = None
    _params = None

    """ True if connected, false otherwise """
    def __bool__(self) :
        if self._client:
            return True
        return False

    """ Gets a simplepoint from ModBus (the SolArk) """
    async def get_datapoint(self):
        simplepoint = {}

        try:
            for key in registers:
                reg = registers[key]
                res = await self._client.read_holding_registers(address=reg[0], count=reg[1], slave=1)
                if not res:
                    continue
                decoder = BinaryPayloadDecoder.fromRegisters(res.registers, byteorder=Endian.BIG, wordorder=Endian.BIG)
                # rather than the loop we could use the decoder for this
                val = 0
                for i in range(0, reg[1]):
                    if (reg[2]):
                        val += decoder.decode_16bit_int() << (16*i)
                    else:
                        val += decoder.decode_16bit_uint() << (16*i)
                simplepoint[key] = val
        except pymodbus.ModbusException as e:
            print(f'modbus exception {e} while getting datapoint')
            self._client = None
            return None
        return simplepoint

    async def reconnect(self):
        connect(self._params)

    async def connect(self, solark_params):
        self._params = solark_params
        try:
            # set up the ModBus RS232 (or RS485) client to talk to the SolArk
            self._client = AsyncModbusSerialClient(
                method='rtu',
                port=self._params['port'],
                baudrate=9600,
                timeout=3,
                parity='N',
                stopbits=1,
                bytesize=8
            )

            # Connect to the SolArk
            if not await self._client.connect():  # Trying for connect to Modbus Server/Slave
                print('Cannot connect to the Modbus Server/Slave')
                self._client = None
                return

            # inverter serial number, this is a nice test that solark communication is working
            s = "SN: "
            res = await self._client.read_holding_registers(address=3, count=5, slave=1)
            if not res:
                print('modbus_client failed to read the SolArk Serial Numer')
                self._client = None
                return
            decoder = BinaryPayloadDecoder.fromRegisters(res.registers, byteorder=Endian.BIG, wordorder=Endian.BIG)
            s += decoder.decode_string(10).decode('utf-8')
            print(f'solark serial number: {s}')
        except pymodbus.ModbusException as e:
            print(f'Exception while connecting to modbus: {e}')
            self._client = None

############# INFLUXDB STUFF ####################

class Influx:
    _client = None
    _params = None

    def __bool__(self) :
        if self._client:
            return True
        return False
    
    """ Converts a "simplepoint" into an influx point.

    A simple point is the most obvious dictionary representation
    of a point. Simply key value pairs encoding all of the values
    we read at a point in time.

    An influxpoint is a special concept related to the influx client
    where we have tags, fields, and timesetamps. The timestamp is
    set automatically on construction.
    """
    def point_to_influxpoint(simplepoint) :
        influxvec = []
        for key in simplepoint:
            reg = registers[key]
            influxvec.append(Point(key))
            influxpoint = influxvec[-1]
            influxpoint.tag("Solark", "1")
            influxpoint.tag("units", reg[3])
            influxpoint.field("value", simplepoint[key])
        return influxvec # a whole vector represents a "point" in time

    """ writes a simplepoint to influxDB """
    async def write_point(self, simplepoint) :
        influxpoint = Influx.point_to_influxpoint(simplepoint)
        return await self.write_influxpoint(influxpoint)

    """ writes an influxpoint to influxDB """
    async def write_influxpoint(self, influxpoint) :
        if not self._client:
            return False
        try:
            for point in influxpoint:
                self._client.write(bucket=self._params['bucket'], record=point)
        except Exception as e:
            print(f'Exception while writing to influx: {e}')
            self._client = None 
            return False
        return True;

    """ Connect with params from our last connection """
    async def reconnect(self):
        connect(_params)


    """ Connect to server """
    async def connect(self, params):
        self._params = params
        try:
            influx_client = InfluxDBClient(
                url=self._params['url'],
                org=self._params['org'],
                token=self._params['token'])
            self._client = influx_client.write_api(write_options=ASYNCHRONOUS)
        except Exception as e:
            print(f'Exception while creating influx client: {e}')
            self._client = None

############## Dummy clients ####################

class DummyMatrix:
    def __bool__(self):
        return True

    async def connect(self, _):
        pass

    async def send_msg(self, msg):
        print(f'would\'ve sent: "{msg}"')

class DummyInflux:
    def __bool__(self):
        return True

    async def connect(self, _):
        pass

    async def write_point(self, point):
        print(f'would\'ve logged: "{str(point)}"')

############## PUTTING IT TOGETHER ####################

message_times = {}

async def clear_alert(matrix, msg, data = None):
    if not matrix:
        return
    if (msg not in message_times):
        return
    message_times.pop(msg, None)  
    print(f'Clearing alert "{msg}"')
    await matrix.send_msg('alert cleared: ' + msg + ' : data=' + str(data))

async def send_alert(matrix, msg, data = None):
    if not matrix:
        return
    t = time.monotonic()
    if (msg in message_times and message_times[msg] + alert_timeout > t):
        return
    message_times[msg] = time.monotonic()
    print(f'Sending alert "{msg}"')
    await matrix.send_msg('alert: ' + msg + ' : data=' + str(data));

async def send_alerts_if_needed(matrix, simplepoint):
    for alert in Alerts:
        val = simplepoint[alert['metric']]
        if alert['fun'](val):
            await send_alert(matrix, alert['msg'],
                    str(alert['metric']) + '='+ str(val))
        else:
            await clear_alert(matrix, alert['msg'],
                    str(alert['metric']) + '='+ str(val))

async def main():
    parser = argparse.ArgumentParser(
        prog='solark_monitor',
        description=
            'Pull data from a solark inverter over modbus, '
            'push the result to influx, '
            'and alert to matrix.'
            'Configuration is done in solark_monitor_config.py.',
    )
    parser.add_argument("-n", "--noalert", action='store_true', dest="noalert", help='use mock instead of actually alerting to matrix')
    parser.add_argument("--nolog", action='store_true', dest="nolog", help='use mock instead of actually logging to influx')
    args = parser.parse_args()
        
    print('Reading from Solark at' + str(solark_params))
    print('Writing to InfluxDB at' + str(influx_params))
    print('Alerting to Matrix at' + str(matrix_params))
    if args.noalert:
        matrix = DummyMatrix()
    else:
        matrix = Matrix()
    await matrix.connect(matrix_params)
    solark = Solark()
    await solark.connect(solark_params)
    if args.nolog:
        influx = DummyInflux()
    else:
        influx = Influx()
    await influx.connect(influx_params)
    while (True):
        if not matrix:
            await matrix.reconnect()

        if not solark:
            await solark.reconnect()
            await send_alert(matrix, "solark modbus not connected")
        else:
            await clear_alert(matrix, "solark modbus not connected")
            
        if not influx:
            influx.reconnect()
            await send_alert(matrix, "influx not connected")
        else:
            await clear_alert(matrix, "influx not connected")

        simplepoint = await solark.get_datapoint()
        if simplepoint is None:
            continue
        await send_alerts_if_needed(matrix, simplepoint)
        await influx.write_point(simplepoint)
        await asyncio.sleep(loop_delay_seconds)

asyncio.run(main())                
