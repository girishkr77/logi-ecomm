import sqlite3
import os
import folium

# Paths to your database and output HTML file
FOLDER_PATH = os.path.expanduser("~/networkpredict")  # <-- Change this to your exact folder name if needed
DB_PATH = os.path.join(FOLDER_PATH, "network_intel.db")
OUTPUT_HTML = os.path.join(FOLDER_PATH, "netguard_coverage_map.html")

def build_interactive_map():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    # Establish connection with the master SQLite database
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    try:
        # Pulling your pre-classified zones and parameters directly from master table
        cur.execute("""
            SELECT zone_lat, zone_lon, visit_count, Networkprovider, zone_status 
            FROM master_zone
        """)
        zones = cur.fetchall()
    except sqlite3.OperationalError:
        print("Schema adjustment check: fetching by basic fields...")
        cur.execute("SELECT zone_lat, zone_lon, visit_count, Networkprovider, zone_status FROM master_zone")
        zones = [z[:3] + ("Unknown", z[3]) for z in cur.fetchall()]
    finally:
        conn.close()

    if not zones:
        print("No master zones found to plot yet. Run data collection and syncing first!")
        return

    # Establish the map center based on the initial entry coordinate
    start_lat, start_lon = zones[0][0], zones[0][1]
    net_map = folium.Map(location=[start_lat, start_lon], zoom_start=14, control_scale=True)

    print(f"Plotting {len(zones)} pre-classified grid tiles onto the interactive coverage map...")

    for lat, lon, visits, provider, status_string in zones:
        # Standardise status format for comparison logic
        status_clean = str(status_string).strip().lower()

        # 1. Clean Map Color Selection Based on Your DB Classified Fields
        if "dead zone" in status_clean:
            color = "red"
            ui_status = "🚨 VERIFIED DEAD ZONE"
        elif "good" in status_clean or "fair" in status_clean or "drop" in status_clean:
            color = "orange"
            ui_status = "⚠️ WARNING SIGNAL AREA"
        else:
            color = "green"
            ui_status = "✅ STABLE COVERAGE ZONE"

        # 2. Design the popup bubble interface text pulling your specific metrics
        popup_text = f"""
        <div style="font-family: Arial, sans-serif; width: 190px; line-height: 1.4;">
            <h4 style="margin:0 0 5px 0; color:{'red' if color=='red' else ('darkorange' if color=='orange' else 'green')};">{ui_status}</h4>
            <b>Grid Box:</b> {lat}, {lon}<br>
            <b>visits:</b> {visits} entries<br>
            <b>Network Provider:</b> <span style="text-transform:uppercase; font-weight:bold;">{provider}</span><br>
            <b>System Flag:</b> {status_string}
        </div>
        """
        
        # 3. Render the bounded circle matching your exact grid resolution blocks
        folium.Circle(
            location=[lat, lon],
            radius=60,  # Covers your localized coordinate spatial block cell resolution
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.35,
            popup=folium.Popup(popup_text, max_width=250)
        ).add_to(net_map)

    # Export map out to a standalone file asset
    net_map.save(OUTPUT_HTML)
    print(f"🎉 Success! Interactive map reflecting DB states saved to: {OUTPUT_HTML}")

if __name__ == "__main__":
    build_interactive_map()
