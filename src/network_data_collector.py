from network_data_prediction import score_and_sync_to_master 
import subprocess
import json
import time
import os
import math
from datetime import datetime
import sqlite3

DB_PATH = os.path.expanduser("~/networkpredict/network_intel.db")
POLLING_INTERVAL = 60  
MAX_STATIONARY_TIME = 300
DISTANCE_THRESHOLD = 50  
DEFAULT_BATTERY_CHECK = 1200

def to_float_or_none(val):
    if val is None or val == "N/A":
        return None
    try:
        return float(val)
    except ValueError:
        return None

def log_new_reading(row_dict, db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("""
        INSERT INTO raw_logs (
            timestamp, Latitude, Longitude, Active_RSRP_dBm, Active_RSRQ_dBm,
            Active_rssi, Active_Level_Bars, Ping_latency, Packet_Loss_Pct,
            NetworkType, Networkprovider, processed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
    """, (
        row_dict["timestamp"],
        to_float_or_none(row_dict["Latitude"]),
        to_float_or_none(row_dict["Longitude"]),
        to_float_or_none(row_dict["Active_RSRP_dBm"]),
        to_float_or_none(row_dict["Active_RSRQ_dBm"]),
        to_float_or_none(row_dict["Active_rssi"]),
        to_float_or_none(row_dict["Active_Level_Bars"]),
        str(row_dict["Ping_latency"]),
        to_float_or_none(row_dict["Packet_Loss_Pct"]),
        str(row_dict["NetworkType"]),
        str(row_dict["Networkprovider"])
    ))
    # Auto-purge processed raw logs to keep phone storage tiny
    cur.execute("DELETE FROM raw_logs WHERE processed = 1")
    # Wipe out any corrupted readings where either Latitude or Longitude is missing
    cur.execute("""
        DELETE FROM raw_logs 
        WHERE Latitude IS NULL 
        OR Longitude IS NULL 
        OR Latitude = '' 
        OR Longitude = ''
    """)
    conn.commit()
    conn.close()

def run_cmd(cmd_list):
    try:
        result = subprocess.run(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        return result.stdout.strip()
    except Exception:
        return ""

def get_battery_level():
    batt_raw = run_cmd(["termux-battery-status"])
    if batt_raw:
        try:
            return json.loads(batt_raw).get("percentage", 100)
        except Exception:
            pass
    return 100

def haversine_distance(lat1, lon1, lat2, lon2):
    if lat1 == "N/A" or lon1 == "N/A" or lat2 is None or lon2 is None:
        return float('inf')  
    try:
        lat1, lon1, lat2, lon2 = map(math.radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        return 6371000 * c
    except ValueError:
        return float('inf')

def collect_and_save_data(lat, lon, acc, prov):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Started full data_collection at {timestamp}...")

    cell_raw = run_cmd(["termux-telephony-cellinfo"])
    device_raw = run_cmd(["termux-telephony-deviceinfo"])
    rsrp, rsrq, level, rssi, networktype, networkprovider = "N/A", "N/A", "N/A", "N/A", "N/A", "N/A"
    
    try:
        cell_data = json.loads(cell_raw)
        device_data = json.loads(device_raw)
        for tower in cell_data:
            if tower.get("registered") is True:
                rsrp = tower.get("rsrp", "N/A")
                rsrq = tower.get("rsrq", "N/A")
                level = tower.get("level", "N/A")
                rssi = tower.get("rssi", "N/A")
                networktype = device_data.get("network_type", "N/A")
                networkprovider = device_data.get("network_operator_name", "N/A")
                break
    except Exception:
        pass 

    ping_raw = run_cmd(["ping", "-c", "4", "8.8.8.8"])
    ping_ms, packet_loss = "TIMEOUT", "100"
    if ping_raw:
        try:
            for line in ping_raw.split('\n'):
                if "packet loss" in line:
                    packet_loss = line.split('%')[0].split()[-1]
                if "rtt min/avg/max/mdev" in line:
                    ping_ms = line.split('=')[1].split('/')[1].strip()
        except Exception:
            pass

    row_dict = {
        "timestamp": timestamp,
        "Latitude": lat,
        "Longitude": lon,
        "Active_RSRP_dBm": rsrp,
        "Active_RSRQ_dBm": rsrq,
        "Active_rssi": rssi,
        "Active_Level_Bars": level,
        "Ping_latency": ping_ms,
        "Packet_Loss_Pct": packet_loss,
        "NetworkType": networktype,
        "Networkprovider": networkprovider
    }

    log_new_reading(row_dict)
    conn = sqlite3.connect(DB_PATH)
    (unprocessed_count) = conn.execute("SELECT COUNT(*) FROM raw_logs WHERE processed = 0").fetchone()
    conn.close()

    if unprocessed_count[0] >= 50:  
        print("50 new readings collected! Auto-syncing to master_zone...")
        score_and_sync_to_master()
        # Wipe out any corrupted readings where either Latitude or Longitude is missing
    print(f"Data committed to SQLite successfully! (RSRP: {rsrp}, Ping: {ping_ms})")

if __name__ == "__main__":
    print(f"Data collection engine started (polling every {POLLING_INTERVAL}s)...")
    
    last_saved_lat = None
    last_saved_lon = None
    last_saved_time = 0.0 
    last_battery_check = 0.0
    battery_level = 100

    try:
        while True:
            current_time = time.time()
            if (current_time - last_battery_check) >= DEFAULT_BATTERY_CHECK:
                battery_level = get_battery_level()
                last_battery_check = current_time
                
            if battery_level < 15:
                print("Battery less than 15%. Stopping data collection engine to save power.")
                run_cmd(["termux-wake-unlock"])
                break

            location_raw = run_cmd(["termux-location", "-p", "gps", "-r", "once"])
            if not location_raw or '"latitude"' not in location_raw:
                print("GPS timed out, checking with Network tracking...")
                location_raw = run_cmd(["termux-location", "-p", "network", "-r", "once"])

            current_lat, current_lon, current_acc, current_prov = "N/A", "N/A", "N/A", "N/A"
            if location_raw:
                try:
                    loc_data = json.loads(location_raw)
                    current_lat = loc_data.get("latitude", "N/A")
                    current_lon = loc_data.get("longitude", "N/A")
                    current_acc = loc_data.get("accuracy", "N/A")
                    current_prov = loc_data.get("provider", "N/A")
                except Exception:
                    print("Failed while parsing location JSON.")

            distance_moved = haversine_distance(current_lat, current_lon, last_saved_lat, last_saved_lon)
            time_elapsed = current_time - last_saved_time

            if distance_moved > DISTANCE_THRESHOLD or time_elapsed > MAX_STATIONARY_TIME:
                if distance_moved > DISTANCE_THRESHOLD:
                    print(f"Location change detected ({round(distance_moved, 1)}m). Collecting data...")
                else:
                    print(f"Stationary for {round(time_elapsed/60, 1)} mins. Collecting heartbeat data...")

                collect_and_save_data(current_lat, current_lon, current_acc, current_prov)
                
                last_saved_lat = current_lat
                last_saved_lon = current_lon
                last_saved_time = current_time
            else:
                print(f"Unchanged ({round(distance_moved, 1)}m, {round(time_elapsed, 1)}s). Skipping.")

            time.sleep(POLLING_INTERVAL)

    except KeyboardInterrupt:
        print("\nForce stopping collector.")
