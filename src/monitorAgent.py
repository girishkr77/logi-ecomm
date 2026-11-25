import subprocess
import json
import time
import os
from datetime import datetime

FOLDER_PATH = os.path.expanduser("~/networkpredict") # <-- Replace with your real folder name
PERF_CSV = os.path.join(FOLDER_PATH, "netguard_perf_log.csv")

def get_process_ram_mb(script_name):
    """Finds a running python script's exact RAM usage using the Linux ps command."""
    try:
        # Look for the python process running the specific script name
        cmd = f"ps -ef | grep {script_name} | grep -v grep | awk '{{print $2}}'"
        pids = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, text=True).stdout.strip().split('\n')
        
        total_ram = 0.0
        for pid in pids:
            if pid.isdigit():
                # Read VmRSS (Physical RAM used) from the Linux proc filesystem
                with open(f"/proc/{pid}/status", "r") as f:
                    for line in f:
                        if "VmRSS:" in line:
                            total_ram += int(line.split()[1]) / 1024.0 # Convert KB to MB
        return round(total_ram, 2)
    except Exception:
        return 0.0

def get_perf_stats():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. Phone Telemetry
    batt_pct, batt_temp = 100, 0.0
    try:
        batt_raw = subprocess.run(["termux-battery-status"], stdout=subprocess.PIPE, text=True, timeout=5).stdout
        batt_data = json.loads(batt_raw)
        batt_pct = batt_data.get("percentage", 100)
        batt_temp = batt_data.get("temperature", 0) / 10.0
    except Exception:
        pass

    # 2. NetGuard Specific Resource Monitoring (Targeted!)
    collector_ram = get_process_ram_mb("network_data_collector.py")
    guard_ram = get_process_ram_mb("livenetworkprediction.py")
    monitor_ram = get_process_ram_mb("monitorAgent.py")
    
    netguard_total_ram_mb = round(collector_ram + guard_ram + monitor_ram, 2)

    return [timestamp, batt_pct, batt_temp, collector_ram, guard_ram, netguard_total_ram_mb]

if __name__ == "__main__":
    if not os.path.exists(PERF_CSV):
        with open(PERF_CSV, "w") as f:
            f.write("timestamp,battery_pct,battery_temp_c,collector_ram_mb,guard_ram_mb,netguard_total_ram_mb\n")

    print(f"NetGuard Precision Performance Monitor active. Logging directly to {PERF_CSV}")
    
    while True:
        try:
            stats = get_perf_stats()
            with open(PERF_CSV, "a") as f:
                f.write(",".join(map(str, stats)) + "\n")
            print(f"[{stats[0]}] Logged. NetGuard Total RAM: {stats[-1]} MB (Collector: {stats[3]} MB, Guard: {stats[4]} MB)")
        except Exception as e:
            print(f"Logging error: {e}")
        time.sleep(600)
