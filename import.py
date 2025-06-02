import socket
import json

# Configuration
UDP_IP = "localhost"   # 10.227.152.9
UDP_PORT = 5666          
JSON_FILE = "Orders\order.json"  

# Read JSON data
with open(JSON_FILE, 'r', encoding='utf-8') as f:
    json_data = f.read()

# Convert to bytes
message = json_data.encode('utf-8')

# Check size (UDP safe limit is ~50 KB max, ideally less)
if len(message) > 50000:
    raise ValueError("JSON file is too large for safe UDP transmission.")

# Create UDP socket and send
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(message, (UDP_IP, UDP_PORT))

print(f"Sent {len(message)} bytes to {UDP_IP}:{UDP_PORT}")