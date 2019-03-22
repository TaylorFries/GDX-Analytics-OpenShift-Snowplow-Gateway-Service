from multiprocessing import Process
from snowplow_tracker import Subject, Tracker, AsyncEmitter
from snowplow_tracker import SelfDescribingJson
from http.server import BaseHTTPRequestHandler, HTTPServer
from jsonschema import validate
from datetime import datetime
from time import sleep
import jsonschema
import psycopg2
import logging
import urllib
import signal
import sys
import json
import os

#log level
INFO=True
DEBUG=True

def logtime():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S:%f")[:-3]

def log(l,s):
    log_line = "{} CAPS [{}]: {}".format(logtime(),l,s)
    if (INFO is not True and l is "INFO") or (DEBUG is not True and l is "DEBUG"):
        return # supress these if the log levels are not True
    elif l is "ERROR" or l is "DEBUG" or l is "INFO":
        print(log_line) # ERROR is not never suppressed

def signal_handler(signal, frame):
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# Retrieve env variables
host = os.getenv('DB_HOSTNAME')
name = os.getenv('DB_NAME')
user = os.getenv('DB_USERNAME')
password = os.getenv('DB_PASSWORD')


# set up dicts to track emitters and trackers
e = {}
t = {}

# Postgres
connect_string = "host={host} dbname={dbname} user={user} password={password}".format(host=host,dbname=name,user=user,password=password)

# Database Query Strings
# Timestamps are in ms and their calculation for insertion as a datetime is handled by postgres, which natively regards datetimes as being in seconds.
client_calls_sql = """INSERT INTO caps.client_calls(received_timestamp,ip_address,response_code,raw_data,environment,namespace,app_id,device_created_timestamp,event_data_json)
                      VALUES(NOW(), %s, %s, %s, %s, %s, %s, TO_TIMESTAMP(%s::decimal/1000), %s) RETURNING request_id ;"""

snowplow_calls_sql = """INSERT INTO caps.snowplow_calls(request_id, sent_timestamp, snowplow_response, try_number,environment,namespace,app_id,device_created_timestamp,event_data_json)
                        VALUES(%s, NOW(), %s, %s, %s, %s, %s, TO_TIMESTAMP(%s::decimal/1000), %s) RETURNING snowplow_send_id ;"""

snowplow_no_call_sql = """INSERT INTO caps.snowplow_calls(request_id)
                                    VALUES(%s) RETURNING snowplow_send_id ;"""

snowplow_select_uncalled = """SELECT * FROM caps.snowplow_calls WHERE try_number IS NULL ;"""

# POST body JSON validation schema
post_schema = json.load(open('post_schema.json', 'r'))

# Create a connection to postgres, and execute a query
# Returns the first column for that insertion, which was the postgres generated identifier
def db_query(sql,execute_tuple,all=False):
    conn = None
    fetch = None
    try:
        conn = psycopg2.connect(connect_string)
        if conn.closed is not 0:
            log("ERROR","Failed to connect to database; check that postgres is running and connection variables are set correctly.")
            sys.exit(1)
        cur = conn.cursor()
        cur.execute(sql,execute_tuple)
        if all:
            fetch = cur.fetchall()
        else:
            fetch = cur.fetchone()
        conn.commit()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()
    return fetch

def call_snowplow(request_id,json_object):
    
    # Use the global emitter and tracker dicts
    global e
    global t

    # callback for passed calls - insert 
    def passed_call(x):
        print()
        snowplow_tuple = (
            str(request_id),
            str(200),
            str(1),
            json_object['env'],
            json_object['namespace'],
            json_object['app_id'],
            json_object['dvce_created_tstamp'],
            json.dumps(json_object['event_data_json'])
        )
        
        snowplow_id = db_query(snowplow_calls_sql, snowplow_tuple)[0]
        log("INFO","Emitter call PASSED on request_id: {} with snowplow_id: {}.".format(request_id,snowplow_id))

    unsent_events = []

    def failed_call(failed_events_count, failed_events):
        # possible backoff-and-retry timeout here
        prev=0
        for i,event in enumerate(failed_events):
            sleep(i + prev)
            prev = i
            snowplow_tuple = (
                str(request_id),
                str(400),
                str(i + 1),
                json_object['env'],
                json_object['namespace'],
                json_object['app_id'],
                json_object['dvce_created_tstamp'],
                json.dumps(json_object['event_data_json'])
            )
            snowplow_id = db_query(snowplow_calls_sql, snowplow_tuple)[0]
            e[tracker_identifier].input(event)
            
            log("INFO","Emitter call FAILED on request_id: {} with snowplow_id: {}.".format(request_id,snowplow_id))

            # for event_dict in y:
            #     print(event_dict)
            #     unsent_events.append(event_dict)

    
    tracker_identifier = json_object['env'] + "-" + json_object['namespace'] + "-" + json_object['app_id']
    log("INFO","New request with tracker_identifier {}".format(tracker_identifier))

    # logic to switch between SPM and Production Snowplow.
    # TODO: Fix SSL problem so to omit the anonymization proxy, since we connect from a Gov IP, not a personal machine
    sp_endpoint = os.getenv("SP_ENDPOINT_{}".format(json_object['env'].upper()))
    log("DEBUG","Using Snowplow Endpoint {}".format(sp_endpoint))

    # Set up the emitter and tracker. If there is already one for this combination of env, namespace, and app-id, reuse it
    # TODO: add error checking
    if tracker_identifier not in e:
        e[tracker_identifier] = AsyncEmitter(sp_endpoint, protocol="https", on_success=passed_call, on_failure=failed_call)
    if tracker_identifier not in t:
        t[tracker_identifier] = Tracker(e[tracker_identifier], encode_base64=False, app_id=json_object['app_id'], namespace=json_object['namespace'])

    # Build event JSON
    # TODO: add error checking
    event = SelfDescribingJson(json_object['event_data_json']['schema'], json_object['event_data_json']['data'])
    # Build contexts
    # TODO: add error checking
    contexts = [] 
    for context in json_object['event_data_json']['contexts']:
        contexts.append(SelfDescribingJson(context['schema'], context['data']))
    
    # Send call to Snowplow
    # TODO: add error checking
    t[tracker_identifier].track_self_describing_event(event, contexts, tstamp=json_object['dvce_created_tstamp'])

# cycles through events that the snowplow emitter did not return 200 on
# def cycle():
#     while True:
#         sleep(10)
#         rows = db_query(snowplow_select_uncalled,None,True)
#         for row in rows:
#             snowplow_id = row[0]
#             request_id = row[1]
#             query = db_query("SELECT environment,namespace,app_id,device_created_timestamp,event_data_json FROM caps.client_calls WHERE request_id = {}".format(request_id),None)
#             environment = query[0]
#             namespace = query[1]
#             app_id = query[2]
#             device_created_timestamp = query[3]
#             event_data_json = json.loads(query[4])
#             # print("{} {} {} {}".format(environment,namespace,app_id,device_created_timestamp))

class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        ip_address = self.client_address[0]

        length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(length).decode('utf-8')

        # Test that the post_data is JSON
        try:
            json_object = json.loads(post_data)
        except (json.decoder.JSONDecodeError,ValueError) as e:
            response_code = 400
            self.send_response(response_code, 'POST body is not parsable as JSON.')
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            post_tuple = (ip_address,response_code,post_data,None,None,None,None,None)
            request_id = db_query(client_calls_sql,post_tuple)[0]
            return
            
        # Test that the JSON matches the expeceted schema
        try:
            jsonschema.validate(json_object, post_schema)
        except (jsonschema.ValidationError, jsonschema.SchemaError ) as e:
            response_code = 400
            self.send_response(response_code, 'POST JSON is not compliant with schema.')
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            post_tuple = (ip_address,response_code,post_data,None,None,None,None,None)
            request_id = db_query(client_calls_sql,post_tuple)[0]
            return

        # Test that the input device_created_timestamp is in ms
        device_created_timestamp = json_object['dvce_created_tstamp']
        if device_created_timestamp < 99999999999: # 11 digits, Sat Mar 03 1973 09:46:39 UTC
            # it's too small to be in seconds
            response_code = 400
            self.send_response(response_code, 'Device Created Timestamp is not in milliseconds.')
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            post_tuple = (ip_address,response_code,post_data,None,None,None,None,None)
            request_id = db_query(client_calls_sql,post_tuple)[0]
            return


        # Input POST is JSON and validates to schema
        response_code = 200
        self.send_response(response_code)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()

        # insert the parsed post body into the client_calls table
        post_tuple = (
            ip_address,
            response_code,
            post_data,
            json_object['env'],
            json_object['namespace'],
            json_object['app_id'],
            json_object['dvce_created_tstamp'],
            json.dumps(json_object['event_data_json'])
        )
        request_id = db_query(client_calls_sql, post_tuple)[0]

        call_snowplow(request_id, json_object)

def serve():
    server_address = ('0.0.0.0', 80)
    httpd = HTTPServer(server_address, RequestHandler)
    log("INFO","Listening for POST requests on port 80.")
    httpd.serve_forever()

if db_query("SELECT 1 ;",None)[0] is not 1:
    log("ERROR","There is a problem querying the database.")
    sys.exit(1)

print("\nGDX Analytics as a Service\n===")
serve()
# Process(target=serve).start()
# Process(target=cycle).start()