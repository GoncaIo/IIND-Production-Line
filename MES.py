from opcua import Client, ua
import time
import sys
import json
import os
from dataclasses import dataclass, field
from typing import List
from collections import deque
from datetime import datetime, timedelta

# --- Definition of Pieces and Tools ---

@dataclass
class Pieces:
    Initial_Piece: int
    TRANSFORM: List[int] = field(default_factory=list)
    TIMES: List[int] = field(default_factory=list)  # In seconds
    wip = False

WH1 = [0] * 32
WH2 = [0] * 32

# --- Buffers para pendências P1 e P2 ---
pending_p1 = deque()
pending_p2 = deque()

# --- Fila de pedidos pendentes ---
prod_order_queue = deque()

cell_queues = {
    4: deque(),
    5: deque(),
    6: deque(),
    7: deque(),
    8: deque(),
    9: deque()
}

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

# Exemplo simplificado do mapeamento de células para tipos de peça
cell_capabilities = {
    3: [4],
    4: [4,5],
    5: [5,6],
    6: [6,7],
    7: [7,8],
    8: [8,9],
    9: [4,5,6],
    10: [7,8,9],
    11: [5,6,7],
    # Ajusta conforme o teu layout e capacidades reais
}

def simulate_transformation_path(p: Pieces):
    current = p.Initial_Piece
    for tool in p.TRANSFORM:
        result = Transformations.get((current, tool))
        if result is None:
            return None
        current = result
    return current

# --- ADICIONADO: Função recursiva para calcular P1 e P2 necessários ---
def calculate_raw_materials_recursive(piece_type, quantity, transform_map=Transformations):
    """
    Calcula recursivamente quantas P1 e P2 são necessárias para produzir `quantity` peças do tipo `piece_type`.
    """
    if piece_type == 1:  # P1
        return {'P1': quantity, 'P2': 0}
    if piece_type == 2:  # P2
        return {'P1': 0, 'P2': quantity}
    
    # Procura a peça inicial que gera a peça atual
    for (init_piece, tool), result_piece in transform_map.items():
        if result_piece == piece_type:
            needs = calculate_raw_materials_recursive(init_piece, quantity, transform_map)
            return needs
    
    # Se não encontrar, assume zero (pode ser peça final ou inválida)
    print(f"Warning: unknown transformation path for piece {piece_type}")
    return {'P1': 0, 'P2': 0}

class BeginLine:
    def __init__(this, entry_node, cell_free, cell_num, piece_type_allowed):
        this.entry_node = entry_node
        this.cell_free_node = cell_free
        this.busy = False
        this.wait = datetime.now()
        this.state = 0
        this.cell_num = cell_num
        this.piece_type_allowed = piece_type_allowed  # 1 para P1, 2 para P2
        this.current_piece = 0

    def start(this):
        if this.busy:
            return False
        cell_free = this.cell_free_node.get_value()
        if not (isinstance(cell_free, (list, tuple)) and cell_free[this.cell_num] == 1):
            return False
        
        # Escolher peça da fila correta
        if this.piece_type_allowed == 1 and pending_p1:
            piece_initial = 1
            pending_p1.popleft()
        elif this.piece_type_allowed == 2 and pending_p2:
            piece_initial = 2
            pending_p2.popleft()
        else:
            return False  # sem peça pendente para este tipo
        
        entry_list = this.entry_node.get_value()
        entry_list[this.cell_num] = piece_initial
        this.entry_node.set_value(ua.Variant(entry_list, ua.VariantType.Int16))
        print(f"BeginLine {this.cell_num}: Sent initial piece P{piece_initial} to line")
        
        this.busy = True
        this.state = 0
        this.current_piece = piece_initial
        return True

    def tick(this):
        cell_free = this.cell_free_node.get_value()
        if cell_free[this.cell_num] == 1 and this.state == 1:
            # Célula terminou de processar peça, colocar no WH1
            try:
                index = WH1.index(0)
                WH1[index] = this.current_piece
                print(f"BeginLine {this.cell_num}: Stored piece P{this.current_piece} in WH1 at position {index}")
            except ValueError:
                print("Warning: WH1 is full, cannot store more pieces")
            this.busy = False
            this.current_piece = 0
        elif cell_free[this.cell_num] == 0 and this.state == 0:
            this.state += 1

class ProdLine:
    def __init__(this, entry_node, trans_m, trans_t, cell_free, cell_steps, m1t, m2t, cell_num):
        this.entry_node = entry_node
        this.trans_m_node = trans_m
        this.trans_t_node = trans_t
        this.cell_free_node = cell_free
        this.cell_steps_node = cell_steps
        this.m1t = m1t
        this.m2t = m2t
        this.cell_num = cell_num
        this.busy = False
        this.wait = datetime.now()
        this.steps = 0
        this.state = 0
        this.piece = 0
    
    def tick(this):
        if(datetime.now() > this.wait and this.busy):
            if(this.state == 0):
                cell_free = this.cell_free_node.get_value()
                if isinstance(cell_free, (list, tuple)) and cell_free[this.cell_num] == 0:
                    print("Cell num",this.cell_num,"State 0 C1 is busy processing...")
                    this.state+=1
                    this.wait = datetime.now() + timedelta(seconds=0.5)

            elif(this.state==1):
                cell_free = this.cell_free_node.get_value()
                if isinstance(cell_free, (list, tuple)) and cell_free[this.cell_num] == 0:
                    print("Cell num",this.cell_num,"State 1 C1 is busy processing...")
                    this.state+=1
                this.wait = datetime.now() + timedelta(seconds=0.5)

            elif(this.state == 2):
                cell_free = this.cell_free_node.get_value()
                if isinstance(cell_free, (list, tuple)) and cell_free[this.cell_num] == 1:
                    this.busy = False
                    # Remove peça da fila da célula, pois terminou processamento
                    if cell_queues[this.cell_num]:
                        finished_piece = cell_queues[this.cell_num].popleft()
                        print(f"ProdLine cell {this.cell_num}: Finished processing piece P{finished_piece}. Queue length now {len(cell_queues[this.cell_num])}")

                        # Armazenar peça no WH2
                        try:
                            index = WH2.index(0)
                            WH2[index] = finished_piece
                            print(f"Stored transformed piece P{finished_piece} in WH2 at position {index}")
                        except ValueError:
                            print("Warning: WH2 is full, cannot store more pieces")

                    else:
                        print(f"Warning: ProdLine cell {this.cell_num} finished processing but queue is empty!")

                    return simulate_transformation_path(this.piece) if this.piece != 0 else None
                else:
                    this.wait = datetime.now() + timedelta(seconds=0.5)

    def start(this, piece):
        if(not this.busy):
            cell_steps = this.cell_steps_node.get_value()
            if not isinstance(cell_steps, (list, tuple)):
                print("Error reading Cell_steps array")
                cell_steps = [0]*21

            cell_steps = list(cell_steps)
            cell_steps[this.cell_num] = len(piece.TRANSFORM) if piece != 0 else 0
            this.cell_steps_node.set_value(ua.Variant(cell_steps, ua.VariantType.Int16))

            if piece != 0:
                entry_list = this.entry_node.get_value()
                entry_list[this.cell_num] = piece.Initial_Piece
                this.entry_node.set_value(ua.Variant(entry_list, ua.VariantType.Int16))

                MAX_TRANS = 6
                tools = piece.TRANSFORM[:MAX_TRANS]
                times = piece.TIMES[:MAX_TRANS]

                while len(tools) < MAX_TRANS:
                    tools.append(0)
                while len(times) < MAX_TRANS:
                    times.append(0)

                times_ms = [t * 1000 for t in times]

                this.trans_m_node.set_value(ua.Variant(tools, ua.VariantType.Int16))
                print("TIMES", times_ms)
                this.trans_t_node.set_value(ua.Variant(times_ms, ua.VariantType.Int64))

                print(f"Sent recipe: P{order_type} → initial {piece.Initial_Piece}, {len(piece.TRANSFORM)} steps")
                
                cell_queues[this.cell_num].append(piece.Initial_Piece)
                print(f"ProdLine cell {this.cell_num}: Started processing piece P{piece.Initial_Piece}. Queue length now {len(cell_queues[this.cell_num])}")

                this.piece = piece
                this.state = 0
                this.busy = True
                return True
            else:
                print("No active piece to send recipe for (piece = 0)")
        return False

class Order:
    def __init__(this, piece : Pieces):
        this.piece = piece
        this.wip = False

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

# --- Após carregar a order_queue e calcular necessidades ---
total_raw_materials = {'P1': 0, 'P2': 0}
for order_type, quantity in order_queue:

    # BeginLine
    needs = calculate_raw_materials_recursive(order_type, quantity)
    total_raw_materials['P1'] += needs['P1']
    total_raw_materials['P2'] += needs['P2']

    # ProdLine
    for _ in range(quantity):
        prod_order_queue.append(order_type)

print("Total P1 needed for all orders:", total_raw_materials['P1'])
print("Total P2 needed for all orders:", total_raw_materials['P2'])

# Preencher buffers pendentes
pending_p1.clear()
pending_p2.clear()
for _ in range(total_raw_materials['P1']):
    pending_p1.append(1)
for _ in range(total_raw_materials['P2']):
    pending_p2.append(2)

# --- OPC UA server connection and processing ---
def read_codesys_variables():
    server_url = "opc.tcp://127.0.0.1:4840"
    client = Client(server_url)

    try:
        client.connect()
        print(f"Connected to OPC UA Server at {server_url}")

        entry_node = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.GVL.Entry_pieces")
        trans_m_node_1 = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.GVL.C1_transformations_M")
        trans_t_node_1 = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.GVL.C1_transformations_T")
        trans_m_node_2 = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.GVL.C2_transformations_M")
        trans_t_node_2 = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.GVL.C2_transformations_T")
        cell_free_node = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.GVL.Cell_free")
        cell_steps_node = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.GVL.Cell_steps")

        entry_list = entry_node.get_value()

        beginLines = [
            BeginLine(entry_node, cell_free_node, 0, piece_type_allowed=1),  # célula 0 só P1
            BeginLine(entry_node, cell_free_node, 1, piece_type_allowed=1),  # célula 1 só P1
            BeginLine(entry_node, cell_free_node, 2, piece_type_allowed=2),  # célula 2 só P2
            BeginLine(entry_node, cell_free_node, 3, piece_type_allowed=2)   # célula 3 só P2
        ]

        prodLines=[
            ProdLine(entry_node, trans_m_node_1, trans_t_node_1, cell_free_node, cell_steps_node, [1,2,3], [2,3,4], 4),
            ProdLine(entry_node, trans_m_node_2, trans_t_node_2, cell_free_node, cell_steps_node, [2,3,4], [3,4,5], 5),
            ProdLine(entry_node, trans_m_node_2, trans_t_node_2, cell_free_node, cell_steps_node, [3,4,5], [4,5,6], 6),
            ProdLine(entry_node, trans_m_node_2, trans_t_node_2, cell_free_node, cell_steps_node, [4,5,6], [5,6,1], 7),
            ProdLine(entry_node, trans_m_node_2, trans_t_node_2, cell_free_node, cell_steps_node, [5,6,1], [6,1,2], 8),
            ProdLine(entry_node, trans_m_node_2, trans_t_node_2, cell_free_node, cell_steps_node, [6,1,2], [1,2,3], 9)
        ]

        while pending_p1 or pending_p2:
            for begin in beginLines:
                begin.start()
            for begin in beginLines:
                if begin.busy:
                    begin.tick()
            time.sleep(0.1)


        # while len(order_queue) > 0:
        #     order_type, quantity = order_queue.popleft()
        #     piece = next((p for p in Piece if simulate_transformation_path(p) == order_type), None)
        #     if not piece:
        #         print(f"No defined transformation path for piece type {order_type}")
        #         return

        #     print(f"Processing order: type={order_type}, quantity={quantity}")

        #     # while(not beginLines[0].start(piece)):
        #     #     pass

        #     # while(beginLines[0].busy):
        #     #     beginLines[0].tick()

        #     while not prodLines[0].start(piece):
        #         pass

        #     result_piece = None
        #     while(prodLines[0].busy):
        #         result_piece = prodLines[0].tick()

        #     if result_piece is None:
        #         print("Error: invalid transformation path for piece or no piece to process")
        #     else:
        #         try:
        #             index = WH2.index(0)
        #             WH2[index] = result_piece
        #             print(f"Stored transformed piece {result_piece} in WH2 at position {index}")

        #             if result_piece == order_type:
        #                 entry_list = entry_node.get_value()
        #                 entry_list[11] = result_piece
        #                 entry_node.set_value(ua.Variant(entry_list, ua.VariantType.Int16))
        #                 print(f"Extracted final piece {result_piece} from WH2 to CX_entry_piece")
        #                 WH2[index] = 0

        #         except ValueError:
        #             print("Warning: WH2 is full, cannot store more pieces")

        while prod_order_queue:
            current_piece_type = prod_order_queue[0]
            piece = next((p for p in Piece if simulate_transformation_path(p) == current_piece_type), None)
            if not piece:
                print(f"No defined transformation path for piece type {current_piece_type}")
                prod_order_queue.popleft()
                continue

            assigned = False
            for cell_num in cell_capabilities.get(current_piece_type, []):
                prod_line = prodLines[cell_num - 4]  # Ajusta índice se necessário
                if not prod_line.busy:
                    if prod_line.start(piece):
                        print(f"Started processing piece P{current_piece_type} on ProdLine cell {cell_num}")
                        prod_order_queue.popleft()
                        assigned = True
                        break
            if not assigned:
                # Nenhuma célula livre para processar agora, aguarda um pouco
                #time.sleep(0.5)
                pass

            # Atualiza o estado das ProdLines
            for prod_line in prodLines:
                if prod_line.busy:
                    result_piece = prod_line.tick()
                    if result_piece is not None:
                        try:
                            index = WH2.index(0)
                            WH2[index] = result_piece
                            print(f"Stored transformed piece {result_piece} in WH2 at position {index}")
                        except ValueError:
                            print("Warning: WH2 is full, cannot store more pieces")


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
