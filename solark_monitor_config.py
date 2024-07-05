matrix_params = {
    'url':'https://matrix.org',
    'user':'@example-account:server',
    'passwd':'your-password',
    'allowlist':['@your-matrix-account:server','your-other-matrix-account'],
}


influx_params = { 
    'token': 'your-influx-token', 
    'bucket': 'your-influx-bucket', 
    'org': 'your-influx-org', 
    'url': 'http://localhost:8083',
} 
 
solark_params = { 
    'port': '/dev/ttyUSB0' 
} 

# Defines the mapping from register numbers to influxpoints. 
# eg. we'll read 1 16bit value from register 166 and put it in 
# the field "Gen Watts" in the resulting influxpoint. 
# True indicates this is a signed value 
registers = { 
    "Faults": (103, 4, False, "Bool"),  
    "Gen Watts": (166, 1, False, "Watts"), 
    "Grid Watts": (169, 1, False, "Watts"), 
    "Inv Watts": (175, 1, True, "Watts"), 
    "Load Watts": (178, 1, False, "Watts"), 
    "Batt SOC": (184, 1, False, "Percent"), 
    "Batt Watts": (190, 1, True, "Watts"), 
    "Grid Live": (194, 1, False, "Bool"), 
    "Gen Freq": (196, 1, False, "Hz"), 
} 
 
Alerts = [
    {'metric':'Faults',
        'fun':lambda x: x!=0,
        'msg':'Solark has Faults Go Check the screen'},
    {'metric':'Grid Live',
        'fun':lambda x: x!=1,
        'msg':'Grid is down running on battery power'},
    {'metric': 'Batt SOC',
        'fun':lambda x: x<10,
        'msg':'Battery is below 10%'},
    {'metric': 'Batt SOC',
        'fun':lambda x: x<20,
        'msg':'Battery is below 20%'},
]

alert_timeout = 24*60*60 # will re-alert in 24 hours

loop_delay_seconds = 10
