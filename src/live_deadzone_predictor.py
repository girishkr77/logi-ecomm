import subprocess
import json
import time
import sqlite3
import os
from lookaheadengine import LookAheadPredictor, haversine_m

DB_PATH = os.path.expanduser("~/networkpredict/network_intel.db")
CHECK_INTERVAL = 10  # Check live GPS every 10 seconds while moving

def get_live_gps():
    try:
        res = subprocess.run(
            ["termux-location", "-p", "gps", "-r", "once"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15
        )
        if res.stdout and '"latitude"' in res.stdout:
            data = json.loads(res.stdout)
            return data.get("latitude"), data.get("longitude")
    except Exception:
        pass
    return None, None

def get_current_provider():
    try:
        res = subprocess.run(
            ["termux-telephony-deviceinfo"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10
        )
        if res.stdout:
            return json.loads(res.stdout).get("network_operator_name", None)
    except Exception:
        pass
    return None

def send_android_alert(title, message):
    # Fires a real Android push notification with vibration
    subprocess.run([
        "termux-notification",
        "--id", "net_guard_alert",
        "--title", title,
        "--content", message,
        "--priority", "high",
        "--vibrate", "300,200,300"
    ])

if __name__ == "__main__":
    # First, print your top 5 closest Dead Zones so you know where to walk/drive to test!
    conn = sqlite3.connect(DB_PATH)
    bad_zones = conn.execute("""
        SELECT zone_id, zone_lat, zone_lon, Networkprovider, reliable_score, visit_count 
        FROM master_zone 
        WHERE zone_status IN ('Dead Zone', 'Poor') 
        LIMIT 5
    """).fetchall()
    conn.close()

    print("=== Known Bad Zones Ready for Live Test ===")
    
    # Corrected unpacking to match all 6 fields returned from the database query
    for bz in bad_zones:
        z_id, z_lat, z_lon, provider_name, score, visits = bz
        center_lat = z_lat + 0.0005
        center_lon = z_lon + 0.0005
        print(f"Zone ID: {z_id} | Center: ({center_lat:.4f}, {center_lon:.4f}) | Carrier: {provider_name} | Score: {score}% | Visits: {visits}")

    predictor = LookAheadPredictor(db_path=DB_PATH, lookahead_m=500, cone_degrees=45)
    provider = get_current_provider()
    print(f"\nLive Network Guard started for carrier: {provider}...\n")

    prev_lat, prev_lon = get_live_gps()
    while prev_lat is None:
        print("Waiting for initial GPS lock...")
        time.sleep(5)
        prev_lat, prev_lon = get_live_gps()

    print(f"Initial GPS locked at ({prev_lat}, {prev_lon}). Start moving!")

    try:
        while True:
            time.sleep(CHECK_INTERVAL)
            curr_lat, curr_lon = get_live_gps()
            if curr_lat is None:
                continue

            moved = haversine_m(prev_lat, prev_lon, curr_lat, curr_lon)
            if moved < 10:
                print(f"Stationary ({round(moved, 1)}m moved). Waiting...")
                continue

            alert = predictor.check_ahead(prev_lat, prev_lon, curr_lat, curr_lon, provider=provider)
            if alert:
                title = f"⚠️ {alert['status']} Ahead ({alert['distance_m']}m)"
                msg = f"Signal drops to {alert['score']}% in {alert['distance_m']}m ({alert['confidence']})."
                print(f"ALERT TRIGGERED: {title} -> {msg}")
                send_android_alert(title, msg)
            else:
                print(f"Moved {round(moved, 1)}m — Path ahead is clear.")

            # Update previous position only after meaningful movement so heading stays accurate
            prev_lat, prev_lon = curr_lat, curr_lon

    except KeyboardInterrupt:
        print("\nLive Network Guard stopped.")
