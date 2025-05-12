from opcua import Client, ua
import time
import sys
import json
import os
from dataclasses import dataclass, field
from typing import List
from collections import deque

# --- Definition of Pieces and Tools ---

@dataclass
class Pieces:
    Initial_Piece: int
    TRANSFORM: List[int] = field(default_factory=list)
    TIMES: List[int] = field(default_factory=list)  # In seconds

# Defined pieces
Piece = [
    Pieces(Initial_Piece=1, TRANSFORM=[1], TIMES=[20]),                   # P3
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2], TIMES=[20, 20]),            # P4
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 3], TIMES=[20, 20, 45]),     # P5
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 3, 4], TIMES=[20, 20, 45, 45]), # P8
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 2], TIMES=[20, 20, 20]),     # P9
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 2, 1], TIMES=[20, 20, 20, 30]) # P11
]

# Tools available per machine
Tools_M = {
    'M1a': [1, 2, 3],
    'M1b': [2, 3, 4],
    'M2a': [2, 3, 4],
    'M2b': [3, 4, 5],
    'M3a': [3, 4, 5],
    'M3b': [4, 5, 6],
    'M4a': [4, 5, 6],
    'M4b': [5, 6, 1],
    'M5a': [5, 6, 1],
    'M5b': [6, 1, 2],
    'M6a': [6, 1, 2],
    'M6b': [1, 2, 3],
}

# Valid transformations: (initial_piece, tool) => resulting_piece
Transformations = {
    (1, 1): 3,
    (3, 2): 4,
    (4, 3): 5,
    (5, 4): 8,
    (5, 6): 7,
    (8, 5): 6,
    (2, 6): 9,
    (9, 5): 10,
    (9, 1): 11,
    (4, 2): 9,
}

# Check if a machine can process a piece type
def can_process(machine: str, piece_type: int):
    tools = Tools_M.get(machine, [])
    for tool in tools:
        if (piece_type, tool) in Transformations:
            return True
    return False

# Tool switching logic
def update_tool(GVL_In, Ioff, prev_state, curr_tool):
    if GVL_In[Ioff+1] == 1 and not prev_state:
        curr_tool = (curr_tool + 1) % 3
    prev_state = GVL_In[Ioff+1]
    return curr_tool, prev_state

# --- Load orders from ERP ---
order_queue = deque()
orders_folder = os.path.join(os.path.dirname(__file__), 'Orders')

for filename in os.listdir(orders_folder):
    if filename.endswith('.json'):
        with open(os.path.join(orders_folder, filename), 'r') as file:
            data = json.load(file)
            for order in data.get("orders", []):
                order_type = order.get("type")
                quantity = order.get("quantity")
                order_queue.append((order_type, quantity))

# --- OPC UA server connection and reading ---
def connect_client():

    server_url = "opc.tcp://127.0.0.1:4840"
    
    client = Client(server_url)

    client.connect()

    return client

def get_node(client, nodeid):
    node = client.get_node(nodeid)
    return node

def get_value(node):
    return node.get_value()

def write_value(node, value, tp = ua.VariantType.Int16):
    node.set_value(ua.Variant(value,tp))
    
def read_codesys_variables():
    server_url = "opc.tcp://127.0.0.1:4840"
    client = Client(server_url)

    try:
        client.connect()
        print(f"Connected to OPC UA Server at {server_url}")

        Warehouse1 = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.int1")

        curr_tool = 0
        prev_state = False
        GVL_In = [0] * 64
        Ioff = 0

        while order_queue:
            order_type, quantity = order_queue.popleft()
            print(f"Processing order: type={order_type}, quantity={quantity}")

            for _ in range(quantity):
                piece_value = order_type
                print(f"\nPiece type to produce: {piece_value}")

                found = False
                for cell in range(1, 7):
                    for side in ['a', 'b']:
                        machine = f"M{cell}{side}"
                        if can_process(machine, piece_value):
                            print(f"Piece {piece_value} can be processed by machine {machine} (Cell C{cell})")
                            found = True
                            break
                    if found:
                        break
                if not found:
                    print(f"No machine available to process piece {piece_value}.")

                Warehouse1.set_value(ua.Variant(piece_value + 1, ua.VariantType.Int16))
                time.sleep(2)

    except KeyboardInterrupt:
        print("\nInterrupted by user. Disconnecting client...")
        client.disconnect()
        print("Client successfully disconnected.")
        sys.exit(0)

    except Exception as e:
        print(f"An error occurred: {e}")
        client.disconnect()
        sys.exit(1)

# --- Main execution ---
if __name__ == "__main__":
    queue = [2,3]
    client = connect_client()
    wanted_node = get_node(client,"ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.wanted_piece"
    



    
