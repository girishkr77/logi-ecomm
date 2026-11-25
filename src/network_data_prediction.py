import sqlite3
import pandas as pd
import numpy as np
import requests  # Make sure to run 'pip install requests' inside your venv
import json

DB_PATH = "network_intel.db"
CSV_PATH = "net_data_collection.csv"  # <-- Put your exact CSV file path here
AWS_SERVER_IP = "10.201.10.40"  # <-- Replace with your real AWS EC2 IP address
AWS_API_URL = f"http://{AWS_SERVER_IP}:5000/upload_zone"
# Define your local path cleanly at the top of your phone script


def push_high_confidence_zones_to_cloud(local_db_path):
    conn = sqlite3.connect(local_db_path)
    cur = conn.cursor()
    
    # 1. Select all zones that have reached our absolute reliability metric (10+ visits)
    cur.execute("""
        SELECT zone_lat, zone_lon, primary_provider, status, visit_count 
        FROM master_zone 
        WHERE visit_count >= 10
    """)
    reliable_zones = cur.fetchall()
    
    if not reliable_zones:
        print("No local zones have reached the 10-visit reliability threshold yet.")
        conn.close()
        return

    print(f"Found {len(reliable_zones)} highly reliable zones ready for cloud offloading...")
    
    uploaded_keys = []
    for lat, lon, provider, status, visits in reliable_zones:
        payload = {
            "zone_lat": lat,
            "zone_lon": lon,
            "primary_provider": provider,
            "status": status,
            "visit_count": visits
        }
        
        try:
            # 2. Transmit the telemetry packet up to AWS
            headers = {'Content-Type': 'application/json'}
            response = requests.post(AWS_API_URL, data=json.dumps(payload), headers=headers, timeout=10)
            
            if response.status_code == 200:
                # Keep track of successfully transmitted entries
                uploaded_keys.append((lat, lon, provider))
        except Exception as e:
            print(f"Cloud transmission pause/error connecting to AWS: {e}")
            break  # Stop processing the queue if connection drops on the road
            
    # 3. Memory Optimization Purge: Clear uploaded entries from local phone tracking
    if uploaded_keys:
        for lat, lon, provider in uploaded_keys:
            cur.execute("""
                DELETE FROM master_zone 
                WHERE zone_lat = ? AND zone_lon = ? AND primary_provider = ?
            """, (lat, lon, provider))
        conn.commit()
        print(f"🚀 Successfully offloaded and local-purged {len(uploaded_keys)} entries to centralized cloud database!")
        
    conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    
    # 1. Raw Logs Table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS raw_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            Latitude REAL,
            Longitude REAL,
            Active_RSRP_dBm REAL,
            Active_RSRQ_dBm REAL,
            Active_rssi REAL,
            Active_Level_Bars REAL,
            Ping_latency TEXT,
            Packet_Loss_Pct REAL,
            NetworkType TEXT,
            Networkprovider TEXT,
            processed INTEGER DEFAULT 0
        )
    """)
    
    # 2. Master Zone Table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS master_zone (
            zone_id TEXT,
            Networkprovider TEXT,
            zone_lat REAL,
            zone_lon REAL,
            visit_count INTEGER,
            reliable_score REAL,
            zone_status TEXT,
            confidence TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            synced_to_aws INTEGER DEFAULT 0,
            PRIMARY KEY (zone_id, Networkprovider)
        )
    """)
    
    cur.execute("CREATE INDEX IF NOT EXISTS idx_zone_coords ON master_zone (zone_lat, zone_lon);")
    conn.commit()
    conn.close()
    print("1. Database and tables initialized successfully!")

def load_csv_once(csv_file):
    conn = sqlite3.connect(DB_PATH)
    df_csv = pd.read_csv(csv_file)
    
    # Keep only columns that exist in raw_logs table so column mismatches don't crash
    valid_cols = [
        "timestamp", "Latitude", "Longitude", "Active_RSRP_dBm", "Active_RSRQ_dBm",
        "Active_rssi", "Active_Level_Bars", "Ping_latency", "Packet_Loss_Pct",
        "NetworkType", "Networkprovider"
    ]
    cols_to_use = [c for c in valid_cols if c in df_csv.columns]
    
    df_csv[cols_to_use].to_sql("raw_logs", conn, if_exists="append", index=False)
    conn.close()
    print(f"2. Loaded {len(df_csv)} rows from CSV into raw_logs!")

def score_and_sync_to_master():
    conn = sqlite3.connect(DB_PATH)
    raw_df = pd.read_sql_query("SELECT * FROM raw_logs WHERE processed = 0", conn)
    
    if raw_df.empty:
        print("No new rows to sync.")
        conn.close()
        return

    raw_ids = tuple(raw_df["id"].tolist())
    
    # Stage 1: Clean & Filter
    df = raw_df[
        raw_df["Latitude"].notna() & raw_df["Latitude"].between(-90, 90) &
        raw_df["Longitude"].notna() & raw_df["Longitude"].between(-180, 180) &
        raw_df["Active_RSRP_dBm"].notna() & raw_df["Active_RSRP_dBm"].between(-155, -30) &
        raw_df["Active_RSRQ_dBm"].notna() & raw_df["Active_RSRQ_dBm"].between(-34, -3) &
        raw_df["Active_rssi"].notna() & raw_df["Active_rssi"].between(-120, -30) &
        raw_df["Active_Level_Bars"].notna() & raw_df["Active_Level_Bars"].between(0, 5) &
        ((raw_df["Ping_latency"] == "TIMEOUT") | pd.to_numeric(raw_df["Ping_latency"], errors="coerce").between(1.0, 5000.0)) &
        raw_df["Packet_Loss_Pct"].notna() & raw_df["Packet_Loss_Pct"].between(0, 100)
    ].copy()

    if not df.empty:
        df["Networkprovider"] = df["Networkprovider"].fillna("Unknown")
        df["Ping_latency"] = pd.to_numeric(df["Ping_latency"].replace("TIMEOUT", 5000.0), errors="coerce")

        # Stage 2: Zone Trimming (~110m blocks)
        df["zone_lat"] = np.floor(df["Latitude"] * 1000) / 1000
        df["zone_lon"] = np.floor(df["Longitude"] * 1000) / 1000
        df["zone_id"] = df["zone_lat"].astype(str) + "_" + df["zone_lon"].astype(str)

        # Stage 3 & 4: Score Metrics
        scores_scale = [100, 80, 60, 40]
        df["rsrp_score"] = np.select(
            [df["Active_RSRP_dBm"] >= -85, df["Active_RSRP_dBm"] >= -95, df["Active_RSRP_dBm"] >= -105, df["Active_RSRP_dBm"] >= -115],
            scores_scale, default=20
        )
        df["rsrq_score"] = np.select(
            [df["Active_RSRQ_dBm"] >= -10, df["Active_RSRQ_dBm"] >= -14, df["Active_RSRQ_dBm"] >= -17, df["Active_RSRQ_dBm"] >= -20],
            scores_scale, default=20
        )
        df["ping_score"] = np.select(
            [df["Ping_latency"] < 40, df["Ping_latency"] < 80, df["Ping_latency"] < 150, df["Ping_latency"] < 300],
            scores_scale, default=20
        )
        df["loss_score"] = np.select(
            [df["Packet_Loss_Pct"] == 0, df["Packet_Loss_Pct"] <= 2, df["Packet_Loss_Pct"] <= 5, df["Packet_Loss_Pct"] <= 15],
            scores_scale, default=20
        )

        df["row_score"] = 0.25 * (df["rsrp_score"] + df["rsrq_score"] + df["ping_score"] + df["loss_score"])
        dead_mask = (df["Packet_Loss_Pct"] > 20) | (df["Ping_latency"] > 500)
        df.loc[dead_mask, "row_score"] = np.minimum(df.loc[dead_mask, "row_score"], 20.0)

        # Aggregate batch
        batch_zones = df.groupby(["zone_id", "Networkprovider", "zone_lat", "zone_lon"], as_index=False).agg(
            new_visits=("row_score", "count"),
            batch_score=("row_score", "median")
        )

        # Merge into master_zone
        cur = conn.cursor()
        for _, row in batch_zones.iterrows():
            cur.execute(
                "SELECT visit_count, reliable_score FROM master_zone WHERE zone_id = ? AND Networkprovider = ?",
                (row["zone_id"], row["Networkprovider"])
            )
            existing = cur.fetchone()
            
            if existing:
                old_visits, old_score = existing
                total_visits = old_visits + int(row["new_visits"])
                final_score = round(((old_score * old_visits) + (row["batch_score"] * row["new_visits"])) / total_visits, 1)
            else:
                total_visits = int(row["new_visits"])
                final_score = round(float(row["batch_score"]), 1)

            status = (
                "Excellent" if final_score >= 85 else
                "Good" if final_score >= 70 else
                "Fair" if final_score >= 50 else
                "Poor" if final_score >= 35 else
                "Dead Zone"
            )
            confidence = "High (3+ visits)" if total_visits >= 3 else ("Medium (2 visits)" if total_visits == 2 else "Low (1 visit)")

            cur.execute("""
                INSERT INTO master_zone (zone_id, Networkprovider, zone_lat, zone_lon, visit_count, reliable_score, zone_status, confidence, synced_to_aws)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(zone_id, Networkprovider) DO UPDATE SET
                    visit_count = excluded.visit_count,
                    reliable_score = excluded.reliable_score,
                    zone_status = excluded.zone_status,
                    confidence = excluded.confidence,
                    last_updated = CURRENT_TIMESTAMP,
                    synced_to_aws = 0
            """, (row["zone_id"], row["Networkprovider"], row["zone_lat"], row["zone_lon"], total_visits, final_score, status, confidence))

    # Mark raw rows processed
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in raw_ids)
    cur.execute(f"UPDATE raw_logs SET processed = 1 WHERE id IN ({placeholders})", raw_ids)
    conn.commit()
    
    # Print verification summary
    summary = pd.read_sql_query("SELECT zone_status, COUNT(*) as count FROM master_zone GROUP BY zone_status", conn)
    conn.close()
    print(f"3. Synced {len(raw_ids)} raw rows! Master Zone breakdown:")
    print(summary)

# --- RUN EVERYTHING NOW ---
if __name__ == "__main__":
    init_db()
    # load_csv_once(CSV_PATH)       # <-- Comment this line out after running it ONCE!
    score_and_sync_to_master()
    push_high_confidence_zones_to_cloud(DB_PATH)
