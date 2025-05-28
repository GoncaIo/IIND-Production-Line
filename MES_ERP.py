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
    Pieces(Initial_Piece=1, TRANSFORM=[1], TIMES=[20]),                             # P3
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2], TIMES=[20, 20]),                      # P4
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 3], TIMES=[20, 20, 45]),               # P5
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 3, 4], TIMES=[20, 20, 45, 45]),        # P8
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 3, 6], TIMES=[20, 20, 45, 30]),        # P7
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 3, 4, 5], TIMES=[20, 20, 45, 45, 30]), # P6 via P8
    Pieces(Initial_Piece=2, TRANSFORM=[6], TIMES=[15]),                             # P9 via P2
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 2], TIMES=[20, 20, 20]),               # P9 via P4
    Pieces(Initial_Piece=2, TRANSFORM=[6, 5], TIMES=[15, 20]),                      # P10 via P9 (P2)
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 2, 5], TIMES=[20, 20, 20, 20]),        # P10 via P9 (P1)
    Pieces(Initial_Piece=2, TRANSFORM=[6, 1], TIMES=[15, 30]),                      # P11 via P9 (P2)
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 2, 1], TIMES=[20, 20, 20, 30])         # P11 via P9 (P1)
]

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

def simulate_transformation_path(p: Pieces):
    current = p.Initial_Piece
    for tool in p.TRANSFORM:
        result = Transformations.get((current, tool))
        if result is None:
            return None
        current = result
    return current

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

# --- OPC UA server connection and processing ---
def read_codesys_variables():
    server_url = "opc.tcp://127.0.0.1:4840"
    client = Client(server_url)

    try:
        client.connect()
        print(f"Connected to OPC UA Server at {server_url}")

        entry_node = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.GVL.Entry_pieces")
        trans_m_node = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.GVL.C1_transformations_M")
        trans_t_node = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.GVL.C1_transformations_T")
        cell_free_node = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.GVL.Cell_free")
        cell_steps_node = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.GVL.Cell_steps")

        entry_list = entry_node.get_value()

        CELL_CA = 0
        CELL_C1 = 4
        CELL_CX = 11

        WH1 = [0] * 32
        WH2 = [0] * 32

        while len(order_queue) > 0:
            order_type, quantity = order_queue.popleft()
            piece = next((p for p in Piece if simulate_transformation_path(p) == order_type), None)
            if not piece:
                print(f"No defined transformation path for piece type {order_type}")
                return

            print(f"Processing order: type={order_type}, quantity={quantity}")

            # Enviar peça inicial para CA enquanto CA estiver livre
            while True:
                cell_free = cell_free_node.get_value()
                if isinstance(cell_free, (list, tuple)):
                    if cell_free[CELL_CA] == 1:
                        entry_list = entry_node.get_value()
                        entry_list[1] = piece.Initial_Piece
                        entry_node.set_value(ua.Variant(entry_list, ua.VariantType.Int16))
                        print(f"Sent initial piece {piece.Initial_Piece} to CA_entry_piece (CA is free)")
                    else:
                        ##entry_list[0] = 0 TALVEZ DESCOMENTAR
                        ##entry_node.set_value(ua.Variant(entry_list, ua.VariantType.Int16))
                        try:
                            index = WH1.index(0)
                            WH1[index] = piece.Initial_Piece
                            print(f"Stored piece {piece.Initial_Piece} in WH1 at position {index} after clearing CA entry")
                            time.sleep(1)
                        except ValueError:
                            print("Warning: WH1 is full, cannot store more pieces")
                        print("CA is busy now, sent 0 to CA_entry_piece")
                        break
                time.sleep(0.5)

            # Esperar C1 estar livre e peça disponível em WH1
            while True:
                cell_free = cell_free_node.get_value()
                piece_available = piece.Initial_Piece in WH1
                if isinstance(cell_free, (list, tuple)):

                    # Aqui: se C1 estiver ocupado, peça a 0
                    if cell_free[CELL_C1] == 0:
                        print("C1 is busy processing...")
                        piece = 0  # Redefinir piece para 0 quando C1 ocupado

                    # Se C1 estiver livre e peça disponível, sair do loop
                    if cell_free[CELL_C1] == 1 and piece_available:
                        index_to_remove = WH1.index(piece.Initial_Piece)
                        WH1[index_to_remove] = 0
                        print(f"Removed piece {piece.Initial_Piece} from WH1 at position {index_to_remove}")
                        break

                if not (isinstance(cell_free, (list, tuple)) and cell_free[CELL_C1] == 1):
                    print("Waiting for C1 to be free...")
                if not piece_available:
                    print(f"Waiting for piece {piece.Initial_Piece} to be available in WH1...")
                time.sleep(0.5)

            # Ler o vetor Cell_steps inteiro (ou ler o valor atual em CELL_C1)
            cell_steps = cell_steps_node.get_value()
            if not isinstance(cell_steps, (list, tuple)):
                print("Error reading Cell_steps array")
                cell_steps = [0]*21  # fallback

            # Atualizar passo do C1 para o número de passos da peça
            cell_steps = list(cell_steps)  # garantir mutável
            cell_steps[CELL_C1] = len(piece.TRANSFORM) if piece != 0 else 0  # evita erro se piece for 0

            # Escrever vetor atualizado para PLC
            cell_steps_node.set_value(ua.Variant(cell_steps, ua.VariantType.Int16))

            # Enviar entrada e transformações para C1, apenas se piece for diferente de 0
            if piece != 0:
                entry_list = entry_node.get_value()
                entry_list[4] = piece.Initial_Piece
                entry_node.set_value(ua.Variant(entry_list, ua.VariantType.Int16))

                MAX_TRANS = 6
                tools = piece.TRANSFORM[:MAX_TRANS]
                times = piece.TIMES[:MAX_TRANS]

                while len(tools) < MAX_TRANS:
                    tools.append(0)
                while len(times) < MAX_TRANS:
                    times.append(0)

                times_ms = [t * 1000 for t in times]

                trans_m_node.set_value(ua.Variant(tools, ua.VariantType.Int16))
                print("TIMES", times_ms)
                trans_t_node.set_value(ua.Variant(times_ms, ua.VariantType.Int64))

                print(f"Sent recipe: P{order_type} → initial {piece.Initial_Piece}, {len(piece.TRANSFORM)} steps")
            else:
                print("No active piece to send recipe for (piece = 0)")

            # Esperar C1 processar (0 ocupado, depois 1 livre)
            while True:
                cell_free = cell_free_node.get_value()
                if isinstance(cell_free, (list, tuple)) and cell_free[CELL_C1] == 0:
                    print("C1 is busy processing...")
                    break
                time.sleep(0.5)

            ##entry_node.set_value(ua.Variant(0, ua.VariantType.Int16))

            while True:
                cell_free = cell_free_node.get_value()
                if isinstance(cell_free, (list, tuple)) and cell_free[CELL_C1] == 1:
                    result_piece = simulate_transformation_path(piece) if piece != 0 else None
                    if result_piece is None:
                        print("Error: invalid transformation path for piece or no piece to process")
                    else:
                        try:
                            index = WH2.index(0)
                            WH2[index] = result_piece
                            print(f"Stored transformed piece {result_piece} in WH2 at position {index}")

                            # Extrair peça final encomendada para CX_entry_piece
                            if result_piece == order_type:
                                entry_list = entry_node.get_value()
                                entry_list[11] = result_piece
                                entry_node.set_value(ua.Variant(entry_list, ua.VariantType.Int16))
                                print(f"Extracted final piece {result_piece} from WH2 to CX_entry_piece")
                                WH2[index] = 0

                        except ValueError:
                            print("Warning: WH2 is full, cannot store more pieces")
                    break
                time.sleep(0.5)

                

    except KeyboardInterrupt:
        print("\nInterrupted by user. Disconnecting client...")
        client.disconnect()
        print("Client successfully disconnected.")
        sys.exit(0)

    except Exception as e:
        print(f"An error occurred: {e}")
        client.disconnect()
        sys.exit(1)

if __name__ == "__main__":
    read_codesys_variables()
