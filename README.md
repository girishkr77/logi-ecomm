Project Title : 
    NetGuard - Predictive Connectivity Intelligence

Problem Statement - 
    Users discover poor network connectivity 0nly after entering low-coverage areas.

Solution - 
    NetGuard continuously collects mobile network telemetry and location data, identifies recurring low-connectivity zones, and proactively alerts users before entering those zones.

key Innovation - 
    Predicts network degradation before it impacts the user.

Business Impact - 
    * Reduced communication failures
    * improved remote workforce productivity
    * Better route and connectivity planning
    * Eliminated Communication Failures: Allows field workers and travellers to defer critical tasks until they exit a predicted dead zone
    * Improved Remote Productivity: Minimises sudden disconnections during corporate VOIP calls, uploads, or syncs.
    * Smarter Route Planning: Empowers logistics and remote teams to plan travel paths based on predicted connectivity profiles.

Tech Stack - 
    • Environment: Termux (Android Linux Environment)
    • Core Language: Python
    • Data Storage: SQLite (On-device local DB), AWS (Cloud analytics/storage)
    • Data Processing: Pandas
    • Data Ingestion: Android GPS & Network Telemetry APIs

Architectural Flexibility (Offline & Hybrid)

NetGuard is engineered to be resilient and fully functional regardless of the user's current network state:
    • Fully Offline Operation: Telemetry collection, local spatial indexing (via SQLite), and predictive proximity alerts run entirely on-device. The system does not require an active internet connection to protect the user from upcoming dead zones.
    • Hybrid Cloud Synchronization: When a stable connection is detected, the device can securely offload aggregated telemetry to the cloud (AWS) for deeper trend analysis, global map updates, and cross-device intelligence syncing.


Core System Modules

To deliver this intelligent, offline-first experience, NetGuard relies on three distinct sub-services running seamlessly in the background:
    • Automated Data Collector: Seamlessly ingests real-time cellular telemetry and high-precision GPS coordinates, handling background logging with minimal battery impact.
    • Predictive Map Generator: Processes the local SQLite database to bucket coordinates (via spatial clustering) and dynamically generates a localized connectivity map, highlighting exact danger zones.
    • Resource & RAM Guard: Actively monitors system memory usage before launching heavy analytical tasks (like Pandas processing), delaying execution if RAM is constrained to ensure the host device remains completely stable.
