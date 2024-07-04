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
from solark_monitor_config import *

############ MATRIX STUFF ################

# TODO: Could be better done with objects that track connectedness
# that would clean up a lot of weirdly located state
client = {
    'matrix': None,
    'modbus': None,
    'influx': None,
}

async def matrix_send_msg(matrix_client, rooms, msg):
    for room in rooms:
        res = await matrix_client.room_send(
            room_id=room,
            message_type="m.room.message",
            content={"msgtype":"m.text", "body":msg}
        )
        if isinstance(res, nio.RoomSendError):
            print(f'Failed to send msg="{msg}" to room="{room}"')
            await clients['matrix'].close()    
            clients['matrix'] = None
            return

async def get_rooms(matrix_client):
    rooms_response = await matrix_client.joined_rooms()
    if isinstance(rooms_response, nio.JoinedRoomsError):
        print(f'failed to query rooms error={rooms}')
        return None
    return rooms_response.rooms

async def list_users(matrix_client, rooms):
    members = set() 
    for room in rooms:
        res = await matrix_client.joined_members(room)
        if isinstance(res, nio.JoinedMembersError):
            print(f'failed to list users in {room}, potential security problem') 
            return None
        members.update(set(i.user_id for i in res.members))
    return members

def is_allowed_users(users):
    extra_users = users.difference(set(MATRIX_ALLOWLIST + [MATRIX_USER]))
    if extra_users:
        return False
    return True

async def callback(room, event):
    print(f'callback called with room={room.room_id}, event={event}')
    user = event.sender
    if not is_allowed_users(set([user])):
        print(f'rejecting invite from {user}') 
        res = await matrix_state['client'].room_leave(room.room_id)
        if isinstance(res, nio.RoomLeaveError):
            print(f'leave of {room} invited by {user} failed with error {res}')
            await client['matrix'].close()
            client['matrix'] = None
            return
    print(f'accepting invite from {user}') 
    res = await matrix_state['client'].join(room.room_id)
    if isinstance(res, nio.JoinError):
        print(f'Join of {room} invited by {user} failed with error {res}')
        await client['matrix'].close()
        client['matrix'] = None
    client['matrix'].rooms.append(room.room_id)

async def create_matrix_client():
    client['matrix'] = nio.AsyncClient(
            matrix_params['url'],
            matrix_params['user'])
    matrix_client = client['matrix']
    print(await matrix_client.login(matrix_params['passwd']))
    await matrix_client.sync()
    matrix_client.add_event_callback(callback, nio.events.invite_events.InviteEvent)
    # Check that we're not broadcasting to anyone we shouldn't
    matrix_client.rooms = await get_rooms(matrix_client);
    rooms = matrix_client.rooms
    if rooms is None:
        print('we are in no rooms? exiting')
        await matrix_client.close()
        return None
    print(f'in rooms: {rooms}')
    #users = await list_users(matrix_client, rooms)
    #if users is None or not is_allowed_users(users):
    #    print(f'extra users! users are {users} destroying client')
    #    await matrix_client.close()


############## SOLARK MODBUST STUFF ######################33

# Gets a influxpoint from the ModBus client (the SolArk)
async def modbus_get_datapoint(modbus_client):
    simplepoint = {}

    try:
        for key in registers:
            reg = registers[key]
            res = await modbus_client.read_holding_registers(address=reg[0], count=reg[1], slave=1)
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
        modbus_client = None
    return simplepoint

async def create_modbus_client():
    try:
        # set up the ModBus RS232 (or RS485) client to talk to the SolArk
        client['modbus'] = AsyncModbusSerialClient(
            method='rtu',
            port=solark_params['port'],
            baudrate=9600,
            timeout=3,
            parity='N',
            stopbits=1,
            bytesize=8
        )
        modbus_client = client['modbus']

        # Connect to the SolArk
        if not await modbus_client.connect():  # Trying for connect to Modbus Server/Slave
            print('Cannot connect to the Modbus Server/Slave')
            client['modbus'] = None
            return

        # inverter serial number, this is a nice test that solark communication is working
        s = "SN: "
        res = await modbus_client.read_holding_registers(address=3, count=5, slave=1)
        if not res:
            print('modbus_client failed to read the SolArk Serial Numer')
            client['modbus'] = None
            return
        decoder = BinaryPayloadDecoder.fromRegisters(res.registers, byteorder=Endian.BIG, wordorder=Endian.BIG)
        s += decoder.decode_string(10).decode('utf-8')
        print(f'solark serial number: {s}')
    except pymodbus.ModbusException as e:
        print(f'Exception while connecting to modbus: {e}')
        client['modbus'] = None

############# INFLUXDB STUFF ####################

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

# writes a influxpoint to influxDB
async def write_influxpoint(influx_client, influxpoint) :
    if not influx_client:
        return
    try:
        for point in influxpoint:
            influx_client.write(bucket=influx_params['bucket'], record=point)
    except Exception as e:
        print(f'Exception while writing to influx: {e}')
        influx_client = None 

def create_influx_client():
    try:
        influx_client = InfluxDBClient(
            url="http://localhost:8083",
            org=influx_params['org'],
            token=influx_params['token'])
        client['influx'] = influx_client.write_api(write_options=ASYNCHRONOUS)
    except Exception as e:
        print(f'Exception while creating influx client: {e}')
        client['influx'] = None

############## PUTTING IT TOGETHER ####################

message_times = {}

async def clear_alert(matrix_client, msg, data = None):
    if not matrix_client:
        return
    if (msg not in message_times):
        return
    message_times.pop(msg, None)  
    print(f'Clearing alert "{msg}"')
    await matrix_send_msg(matrix_client, matrix_client.rooms,
            'alert cleared: ' + msg + ' : data=' + str(data))

async def send_alert(matrix_client, msg, data = None):
    if not matrix_client:
        return
    t = time.monotonic()
    if (msg in message_times and message_times[msg] + alert_timeout > t):
        return
    message_times[msg] = time.monotonic()
    print(f'Sending alert "{msg}"')
    await matrix_send_msg(matrix_client, matrix_client.rooms,
            'alert: ' + msg + ' : data=' + str(data));

async def send_alerts_if_needed(matrix_client, simplepoint):
    for alert in Alerts:
        val = simplepoint[alert['metric']]
        if alert['fun'](val):
            await send_alert(matrix_client, alert['msg'],
                    str(alert['metric']) + '='+ str(val))
        else:
            await clear_alert(matrix_client, alert['msg'],
                    str(alert['metric']) + '='+ str(val))

async def main():
    print('Reading from Solark at' + str(solark_params))
    print('Writing to InfluxDB at' + str(influx_params))
    print('Alerting to Matrix at' + str(matrix_params))
    await create_matrix_client()
    await create_modbus_client()
    create_influx_client()
    while (True):
        if not client['matrix']:
            await create_matrix_client()
        matrix_client = client['matrix']

        if not client['modbus']:
            await create_modbus_client()
            await send_alert(matrix_client, "modbus not connected")
        else:
            await clear_alert(matrix_client, "modbus not connected")
        modbus_client = client['modbus']
            
        if not client['influx'] :
            createInfluxClient()
            await send_alert(matrix_client, "influx not connected")
        else:
            await clear_alert(matrix_client, "influx not connected")
        influx_client = client['influx']

        simplepoint = await modbus_get_datapoint(modbus_client)
        await send_alerts_if_needed(matrix_client, simplepoint)
        influxpoint = point_to_influxpoint(simplepoint) 
        await write_influxpoint(influx_client, influxpoint)
        await asyncio.sleep(10)

asyncio.run(main())                
