from opcua import Client, ua
import time
import sys
import json
import os
from dataclasses import dataclass, field
from typing import List
from collections import deque
from datetime import datetime, timedelta
import threading
import traceback

# --- Definition of Pieces and Tools ---

teste = True

@dataclass
class Pieces:
    Initial_Piece: int
    TRANSFORM: List[int] = field(default_factory=list)
    TIMES: List[int] = field(default_factory=list)  # In seconds
    Steps: int = 0
    Curr_steps: int = 0


@dataclass
class piece:
    initial_piece: int
    transformations: List[int]
    times: List[int]  # times in ms
    n_steps: int

    def to_array(self, max_steps=6):
        arr = [0] * (2 + 2 * max_steps)
        arr[0] = self.initial_piece
        arr[1] = self.n_steps
        for i in range(max_steps):
            arr[2 + i] = self.transformations[i] if i < self.n_steps else 0
            arr[2 + max_steps + i] = self.times[i] if i < self.n_steps else 0
        return arr


WH1 = [0] * 32
WH2 = [0] * 32

pending_p1 = deque()
pending_p2 = deque()
prod_order_queue = deque()
cell_queues = {4: deque(), 5: deque(), 6: deque(), 7: deque(), 8: deque(), 9: deque()}
remove_queue = deque()
sentBackQueue = deque()

Piece = [
    Pieces(Initial_Piece=1, TRANSFORM=[1], TIMES=[20000], Steps=1),
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2], TIMES=[20000, 20000], Steps=2),
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 3], TIMES=[20000, 20000, 45000], Steps=3),
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 3, 4], TIMES=[20000, 20000, 45000, 45000], Steps=4),
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 3, 6], TIMES=[20000, 20000, 45000, 30000], Steps=4),
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 3, 4, 5], TIMES=[20000, 20000, 45000, 45000, 30000], Steps=5),
    Pieces(Initial_Piece=2, TRANSFORM=[6], TIMES=[15000], Steps=1),
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 2], TIMES=[20000, 20000, 20000], Steps=3),
    Pieces(Initial_Piece=2, TRANSFORM=[6, 5], TIMES=[15000, 20000], Steps=2),
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 2, 5], TIMES=[20000, 20000, 20000, 20000], Steps=4),
    Pieces(Initial_Piece=2, TRANSFORM=[6, 1], TIMES=[15000, 30000], Steps=2),
    Pieces(Initial_Piece=1, TRANSFORM=[1, 2, 2, 1], TIMES=[20000, 20000, 20000, 30000], Steps=4),
]

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

cell_capabilities = {
    3: [4],
    4: [4, 5],
    5: [5, 6],
    6: [6, 7],
    7: [7, 8],
    8: [8, 9],
    9: [4, 5, 6],
    10: [7, 8, 9],
    11: [5, 6, 7],
}

# Map cell numbers (4-9) to their available tools (from your Machine Tools list)
cell_tools = {
    4: [1, 2, 3, 4],  # M1a e M1b
    5: [2, 3, 4, 5],  # M2a e M2b
    6: [3, 4, 5, 6],  # M3a e M3b
    7: [4, 5, 6, 1],  # 
    8: [5, 6, 1, 2],  # 
    9: [6, 1, 2, 3],  # 
}


def cell_can_process(piece: Pieces, cell_num: int, tools_num=4):
    """Check if the cell has all tools needed for the piece's transformation."""
    tools_needed = set(piece.TRANSFORM[0:tools_num])
    tools_needed.discard(0)
    tools_available = set(cell_tools.get(cell_num, []))
    return tools_needed.issubset(tools_available)


def simulate_transformation_path(p: Pieces):
    current = p.Initial_Piece
    for tool in p.TRANSFORM:
        if tool == 0:
            return current
        result = Transformations.get((current, tool))
        if result is None:
            return None
        current = result
    return current

def simulate_trans(p: Pieces):
    current = p.Initial_Piece
    for i in range(0,p.Curr_steps,1):
        result = Transformations.get((current, p.TRANSFORM[i]))
        if result is None:
            return None
        current = result
    return current

def apply_trans(p: Pieces):
    p.Initial_Piece = simulate_trans(p)
    p.TIMES = [i for i in p.TIMES[p.Curr_steps:] if i != 0]
    p.TRANSFORM = [i for i in p.TRANSFORM[p.Curr_steps:] if i != 0]
    p.Steps -= p.Curr_steps
    p.Curr_steps = 0
    return p
    


def calculate_raw_materials_recursive(
    piece_type, quantity, transform_map=Transformations
):
    if piece_type == 1:
        return {"P1": quantity, "P2": 0}
    if piece_type == 2:
        return {"P1": 0, "P2": quantity}
    for (init_piece, tool), result_piece in transform_map.items():
        if result_piece == piece_type:
            needs = calculate_raw_materials_recursive(
                init_piece, quantity, transform_map
            )
            return needs
    print(f"Warning: unknown transformation path for piece {piece_type}")
    return {"P1": 0, "P2": 0}

def cell_name(cell_num):
    # Map cell numbers to names (U1-U6 for 4-9, UA-UD for 0-3)
    if 4 <= cell_num <= 9:
        return f"Cell {cell_num - 3}"
    elif 0 <= cell_num <= 3:
        return f"Cell {chr(ord('A') + cell_num)}"
    else:
        return f"Cell{cell_num}"

def log(msg, context=None, cell_num=None):
    prefix = ""
    if cell_num is not None:
        prefix += f"{cell_name(cell_num)} - "
    print(f"{prefix}{msg}")

def print_prod_order_queue():
    print(f"Pedidos na fila: {list(prod_order_queue)}")
    print(f"WH1: {WH1}")
    print(f"WH2: {WH2}")
    
def send_piece_to_codesys(client, node_prefix, piece: Pieces, cell_num=None):
    node_initial = client.get_node(f"{node_prefix}.Initial_Piece")
    node_tool = client.get_node(f"{node_prefix}.TOOL")
    node_times = client.get_node(f"{node_prefix}.TIMES")
    node_steps = client.get_node(f"{node_prefix}.Steps")
    curr_steps = client.get_node(f"{node_prefix}.Curr_steps")
    ##piece.Initial_Piece = simulate_trans(piece)
    ##piece.TRANSFORM = piece.TRANSFORM[piece.Curr_steps:]
    ##piece.TIMES = piece.TIMES[piece.Curr_steps:]
    ##piece.Steps -= piece.Curr_steps
    ##piece.Curr_steps = 0
    tools_arr = piece.TRANSFORM + [0] * (6 - len(piece.TRANSFORM))
    times_arr = [t for t in piece.TIMES] + [0] * (6 - len(piece.TIMES))
    node_initial.set_value(0,ua.VariantType.Int16)
    time.sleep(0.25)
    node_initial.set_value(piece.Initial_Piece, ua.VariantType.Int16)
    node_tool.set_value(ua.Variant(tools_arr, ua.VariantType.Int16))
    node_times.set_value(ua.Variant(times_arr, ua.VariantType.Int64))
    node_steps.set_value(ua.Variant(piece.Steps, ua.VariantType.Int16))
    curr_steps.set_value(ua.Variant(piece.Curr_steps, ua.VariantType.Int16))
    # Fix: use cell_num for logging, not node_prefix
    log(
        f"Recebeu: Initial={piece.Initial_Piece}, TOOL={tools_arr}, TIMES={times_arr}, Steps={len(piece.TRANSFORM)}",
        cell_num=cell_num
    )

class BeginLine:
    def __init__(this, entry_node, cell_free_node, cell_num, piece_type_allowed):
        this.entry_node = entry_node
        this.cell_free_node = cell_free_node  # agora é um nó booleano individual
        this.busy = False
        this.wait = datetime.now()
        this.state = 0
        this.cell_num = cell_num
        this.piece_type_allowed = piece_type_allowed
        this.current_piece = 0

    def start(this):
        if this.busy:
            return False
        cell_free = this.cell_free_node.get_value()
        if not cell_free:
            return False
        if this.piece_type_allowed == 1 and pending_p1:
            piece_initial = 1
            pending_p1.popleft()
        elif this.piece_type_allowed == 2 and pending_p2:
            piece_initial = 2
            pending_p2.popleft()
        else:
            return False
        entry_list = this.entry_node.get_value()
        entry_list[this.cell_num] = piece_initial
        this.entry_node.set_value(ua.Variant(entry_list, ua.VariantType.Int16))
        log(
            f"Sent initial piece P{piece_initial} to line",
            cell_num=this.cell_num,
        )
        this.busy = True
        this.state = 0
        this.current_piece = piece_initial
        return True

    def tick(this):
        cell_free = this.cell_free_node.get_value()
        if cell_free and this.state == 1:
            try:
                index = WH1.index(0)
                WH1[index] = this.current_piece
                log(
                    f"Stored piece P{this.current_piece} in WH1 at position {index}",
                    cell_num=this.cell_num,
                )
            except ValueError:
                log(
                    "WH1 is full, cannot store more pieces",
                    cell_num=this.cell_num,
                )
            this.busy = False
            this.current_piece = 0
        elif not cell_free and this.state == 0:
            this.state += 1

class ProdLine:
    def __init__(this, cell_num, piece_node_prefix, cell_free_node, cell_queues, end_piece_node, l_free_nodes):
        this.cell_num = cell_num
        this.piece_node_prefix = piece_node_prefix
        this.cell_free_node = cell_free_node  # agora é um nó booleano individual
        this.cell_queues = cell_queues
        this.end_piece_node = end_piece_node
        this.l_free_node = l_free_nodes
        # busy agora é uma propriedade dinâmica
        this.wait = datetime.now()
        this.state = 0
        this.piece = None

    @property
    def busy(this):
        # A linha está ocupada se houver 3 ou mais peças em processamento
        return len(this.cell_queues[this.cell_num]) >= 3

    def tick(this):
        if datetime.now() > this.wait:
            cell_free = this.cell_free_node.get_value()
            end_free = this.l_free_node.get_value()
            if this.state == 0:
                if not end_free:
                    log(
                        "State 1: busy processing...",
                        cell_num=this.cell_num,
                    )
                    node_initial = client.get_node(f"{this.end_piece_node}.Initial_Piece")
                    node_tool = client.get_node(f"{this.end_piece_node}.TOOL")
                    node_times = client.get_node(f"{this.end_piece_node}.TIMES")
                    node_steps = client.get_node(f"{this.end_piece_node}.Steps")
                    node_cursteps = client.get_node(f"{this.end_piece_node}.Curr_steps")
                    ninit = node_initial.get_value()
                    ntool = node_tool.get_value()
                    ntime = node_times.get_value()
                    nsteps = node_steps.get_value()
                    csteps = node_cursteps.get_value()
                    this.p = Pieces(Initial_Piece=ninit,TRANSFORM=ntool,TIMES=ntime,Steps=nsteps,Curr_steps=csteps)
                    this.state += 1
                this.wait = datetime.now() + timedelta(seconds=0.5)
            elif this.state == 1:
                if end_free:
                    # Ao terminar o processamento, remove apenas a previsão da peça da fila
                    if this.cell_queues[this.cell_num]:
                        saida_prevista = this.cell_queues[this.cell_num].popleft()
                        log(
                            f"Finished processing piece (previsão saída: P{saida_prevista}). Queue length now {len(this.cell_queues[this.cell_num])}",
                            cell_num=this.cell_num,
                        )
                    else:
                        log(
                            "Finished processing but queue is empty!",
                            cell_num=this.cell_num,
                        )

                    

                    

                    this.state = 0
                    # busy será recalculado automaticamente pela propriedade
                    return this.p
                else:
                    this.wait = datetime.now() + timedelta(seconds=0.5)

    def start(this, piece_in: Pieces):
        # Só inicia se houver menos de 3 peças na fila da célula
        if datetime.now() > this.wait and len(this.cell_queues[this.cell_num]) < 3:
            # Envia comando para retirar a peça do WH1, mas só confirma quando free_O ficar False
            try:
                idx = WH1.index(piece_in.Initial_Piece)
                # Não retira ainda, apenas guarda o índice para retirar depois
                # Envia comando para a célula pegar a peça
                saida_prevista = simulate_transformation_path(piece_in)
                # Pass cell_num to send_piece_to_codesys for correct logging
                send_piece_to_codesys(client, this.piece_node_prefix, piece_in, cell_num=this.cell_num)
                this.piece = piece_in
                this.state = 0
                # Guardar o pending_wh1_remove para esta célula
                if not hasattr(ProdLine, "pending_wh1_remove"):
                    ProdLine.pending_wh1_remove = {}
                ProdLine.pending_wh1_remove[this.cell_num] = (idx, piece_in.Initial_Piece)
                this.wait = datetime.now() + timedelta(seconds=1)
                return saida_prevista  # Retorna a previsão para ser usada fora
            except ValueError:
                log(
                    f"Erro, não há P{piece_in.Initial_Piece} no WH1!",
                    cell_num=this.cell_num,
                )
        return None

class EndLine:
    def __init__(this, entry_node, cell_free_node, cell_num, node_prefix):
        this.entry_node = entry_node
        this.first_cell_free = cell_free_node
        this.cell_num = cell_num
        this.cap = 6
        this.node_prefix = node_prefix

    def putPiece(this, piece):
        if(this.cap > 0):
            if(this.first_cell_free.get_value() == 1):
                this.cap -= 1
                send_piece_to_codesys(client, this.node_prefix, Pieces(WH2[piece],TRANSFORM=[0,0,0,0,0,0],TIMES=[0,0,0,0,0,0],Steps=0), cell_num=this.cell_num)
                return True
        return False

class Order:
    def __init__(this, piece: Pieces):
        this.piece = piece
        this.wip = False


# --- Load orders from ERP ---
order_queue = deque()
orders_folder = os.path.join(os.path.dirname(__file__), "Orders")
for filename in os.listdir(orders_folder):
    if filename.endswith(".json"):
        with open(os.path.join(orders_folder, filename), "r") as file:
            data = json.load(file)
            for order in data.get("orders", []):
                order_type = order.get("type")
                quantity = order.get("quantity")
                # Check for invalid piece type (menor que 3 ou maior que 11)
                if (isinstance(order_type, int) and (order_type > 11 or order_type < 3)) or (isinstance(order_type, tuple) and (order_type[0] > 11 or order_type[0] < 3)):
                    print(f"Erro: Peça {order_type} fora do intervalo permitido (3-11). Ignorando pedido.")
                    continue
                order_queue.append((order_type, quantity))
# --- Após carregar a order_queue e calcular necessidades ---
total_raw_materials = {"P1": 0, "P2": 0}
for order_type, quantity in order_queue:
    # Ajuste para decomposição: se for (6, 8), peça inicial é 8
    if (isinstance(order_type, int) and (order_type > 11 or order_type < 3)) or (isinstance(order_type, tuple) and (order_type[0] > 11 or order_type[0] < 3)):
        print(f"Erro: Peça {order_type} fora do intervalo permitido (3-11). Ignorando pedido.")
        continue
    needs = calculate_raw_materials_recursive(order_type, quantity)
    total_raw_materials["P1"] += needs["P1"]
    total_raw_materials["P2"] += needs["P2"]
    for _ in range(quantity):
        prod_order_queue.append(order_type)
log(f"Total P1 needed for all orders: {total_raw_materials['P1']}")
log(f"Total P2 needed for all orders: {total_raw_materials['P2']}")
pending_p1.clear()
pending_p2.clear()
for _ in range(total_raw_materials["P1"]):
    pending_p1.append(1)
for _ in range(total_raw_materials["P2"]):
    pending_p2.append(2)
print_prod_order_queue()



def print_cell_queue(cell_num):
    fila = list(cell_queues[cell_num])
    print(f"{cell_name(cell_num)} - fila: {fila}")

def prodline_worker(prod_line):
    while True:
        result_piece = prod_line.tick()
        if result_piece is not None:
            try:
                idx = WH2.index(0)
                print("Trying to remove piece",result_piece,"'\n")
                WH2[idx] = simulate_trans(result_piece)
                print("Simulated trans is ",WH2[idx],'\n\n')
                remove_queue.append(apply_trans(result_piece))
                print("Remove queue",remove_queue)
            except ValueError:
                print(f"WH2 is full, cannot store more pieces (Célula {prod_line.cell_num})")
        time.sleep(0.1)

def mes_main_loop(beginLines, prodLines, end_lines, cell_free_nodes, l_free_nodes):
    eod_node = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.GVL.End_of_day")
    prev_l_free = {cell_num: l_free_nodes[cell_num].get_value() for cell_num in range(4, 10)}
    prev_cell_free = {cell_num: cell_free_nodes[cell_num].get_value() for cell_num in range(4, 10)}
    # Controle para detectar flanco negativo (True->False) de free_O de cada célula
    prev_cell_free_negedge = {cell_num: cell_free_nodes[cell_num].get_value() for cell_num in range(4, 10)}
    prev_sent_back_l_free = l_free_nodes[10].get_value()
    # Lista de pedidos pendentes para cada célula (aguardando flanco negativo)
    pending_queue_add = {}
    pending_orders = set()  # Track orders waiting for confirmation
    sendBackBreak = datetime.now()

    ##end = datetime.now() + timedelta(seconds=60)

    # Iniciar uma thread para cada ProdLine
    for prod_line in prodLines:
        t = threading.Thread(target=prodline_worker, args=(prod_line,), daemon=True)
        t.start()

    while True:
        # Atualizar o estado de cell_free_node de cada linha antes de qualquer decisão
        for prod_line in prodLines:
            prod_line.cell_free_node = cell_free_nodes[prod_line.cell_num]
        for begin in beginLines:
            begin.cell_free_node = cell_free_nodes[begin.cell_num]

        # Monitorar flanco positivo de L1.free_O a L6.free_O (mantém para debug/visualização)
        for cell_num in range(4, 10):
            curr_l_free = l_free_nodes[cell_num].get_value()
            prev_l_free[cell_num] = curr_l_free

        # Alimentar linhas de entrada
        for begin in beginLines:
            begin.cell_free_node = cell_free_nodes[begin.cell_num]
            begin.start()
        for begin in beginLines:
            if begin.busy:
                begin.tick()

        #Enviar as peças que foram enviadas de volta (EX: P7)
        if len(sentBackQueue) > 0:
            curPiece = sentBackQueue[0]
            stop = False
            for i in range(4,0,-1):
                if not stop:
                    for cell_num in range(4, 10):
                        prod_line = prodLines[cell_num - 4]
                        prod_line.cell_free_node = cell_free_nodes[cell_num]
                        cell_free = prod_line.cell_free_node.get_value()
                        if (
                            cell_free
                            and len(cell_queues[cell_num]) < 2
                            and cell_can_process(curPiece, cell_num,i)
                            and curPiece.Initial_Piece in WH1
                            and cell_num not in pending_queue_add
                        ):
                            saida_prevista = prod_line.start(curPiece)
                            if saida_prevista is not None:
                                pending_queue_add[cell_num] = saida_prevista
                                log(
                                    f"Started processing *returned* piece P{curPiece.Initial_Piece} on ProdLine (aguardando flanco negativo)",
                                    cell_num=cell_num,
                                )
                                sentBackQueue.pop()
                                print("Sent back popped size",len(sentBackQueue))
                                print_cell_queue(cell_num)
                                stop = True




        # Processar ordens de produção: verifica qual célula pode processar e manda a receita
        if prod_order_queue:
            current_piece_type = prod_order_queue[0]
            # Só processa se não estiver pendente de confirmação
            if current_piece_type not in pending_orders:
                # Ajuste para decomposição: se for (6, 8), buscar peça com Initial_Piece=8 e TRANSFORM terminando em 6
                if isinstance(current_piece_type, tuple) and current_piece_type[0] == 6 and current_piece_type[1] == 8:
                    piece = next(
                        (p for p in Piece if p.Initial_Piece == 8 and p.TRANSFORM and p.TRANSFORM[-1] == 6),
                        None,
                    )
                else:
                    piece = next(
                        (
                            p
                            for p in Piece
                            if simulate_transformation_path(p) == current_piece_type
                        ),
                        None,
                    )
                if piece:
                    stop = False
                    for i in range(4,0,-1):
                        if not stop:
                            for cell_num in range(4, 10):
                                prod_line = prodLines[cell_num - 4]
                                prod_line.cell_free_node = cell_free_nodes[cell_num]
                                cell_free = prod_line.cell_free_node.get_value()
                                for i in range(4,0,-1):
                                    if (
                                        cell_free
                                        and len(cell_queues[cell_num]) < 2
                                        and cell_can_process(piece, cell_num, i)
                                        and piece.Initial_Piece in WH1
                                        and cell_num not in pending_queue_add
                                    ):
                                        saida_prevista = prod_line.start(piece)
                                        if saida_prevista is not None:
                                            pending_queue_add[cell_num] = saida_prevista
                                            pending_orders.add(current_piece_type)  # Mark as pending
                                            log(
                                                f"Started processing piece P{current_piece_type} on ProdLine (aguardando flanco negativo de free_O para entrar na fila)",
                                                cell_num=cell_num,
                                            )
                                            print_cell_queue(cell_num)
                                            stop = True


        # Após mandar a receita, monitora flanco negativo de free_O para cada célula
        for cell_num in list(pending_queue_add.keys()):
            curr_cell_free = cell_free_nodes[cell_num].get_value()
            # Flanco negativo: True -> False
            if prev_cell_free_negedge[cell_num] and not curr_cell_free:
                saida_prevista = pending_queue_add[cell_num]
                cell_queues[cell_num].append(saida_prevista)
                # Remover a peça inicial correspondente do WH1 ao entrar na fila da célula
                piece_initial = None
                # Encontrar a peça inicial correspondente ao tipo saida_prevista
                for p in Piece:
                    if simulate_transformation_path(p) == saida_prevista:
                        piece_initial = p.Initial_Piece
                        break
                if piece_initial is not None and piece_initial in WH1:
                    idx = WH1.index(piece_initial)
                    WH1[idx] = 0
                    log(f"Removida peça inicial P{piece_initial} do WH1 ao entrar na fila da célula {cell_num}", cell_num=cell_num)
                log(
                    f"Peça {saida_prevista} entrou na fila da célula {cell_num} (flanco negativo de free_O)",
                    cell_num=cell_num,
                )
                print_cell_queue(cell_num)
                # Remove o pedido da fila e do pending_orders
                if prod_order_queue and prod_order_queue[0] == saida_prevista:
                    prod_order_queue.popleft()
                    pending_orders.discard(saida_prevista)
                else:
                    try:
                        prod_order_queue.remove(saida_prevista)
                    except ValueError:
                        pass
                    pending_orders.discard(saida_prevista)
                print_prod_order_queue()
                del pending_queue_add[cell_num]
            prev_cell_free_negedge[cell_num] = curr_cell_free
            

        # Adiciona controle para remoção da fila apenas no flanco negativo de free_O
        for cell_num in range(4, 10):
            curr_l_free = l_free_nodes[cell_num].get_value()
            # Se havia peça na fila e free_O passou de True para False, remove da fila
            if not prev_l_free[cell_num] and curr_l_free:
                if cell_queues[cell_num]:
                    removed = cell_queues[cell_num].popleft()
                    log(f"Peça removida da fila da célula {cell_num} devido a flanco negativo de U{cell_num-3}.free_O: {removed}", cell_num=cell_num)
                    # Adiciona a peça removida no WH2
                    try:
                        index = WH2.index(0)
                        WH2[index] = removed
                        print(f"Stored transformed piece {removed} in WH2 at position {index} (Célula {cell_num})")
                    except ValueError:
                        print(f"WH2 is full, cannot store more pieces (Célula {cell_num})")
                    print_cell_queue(cell_num)
            prev_l_free[cell_num] = curr_l_free

        if(len(remove_queue) > 0):
            curPiece = remove_queue[0]
            cpIdx = simulate_trans(curPiece)
            endIdx = simulate_transformation_path(curPiece)
            whPos = WH2.index(cpIdx)
            if cpIdx == endIdx:
                placed = False
                for line in end_lines:
                    print("Tried in line",line.cell_num)
                    if(not placed and line.putPiece(whPos)):
                        print("Allegedly added piece")
                        remove_queue.pop()
                        WH2[whPos] = 0
                        placed = True
                        break
            elif sendBackBreak < datetime.now():
                if cell_free_nodes[10].get_value():
                    print("Cell free, sending back.")
                    curPiece = apply_trans(curPiece)
                    print("Applied transformation to piece. Now sending back:",curPiece)
                    send_piece_to_codesys(client, "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UT.piece_I", curPiece, cell_num=10)
                    remove_queue.pop()
                    WH2[whPos] = 0
                    sendBackBreak = datetime.now() + timedelta(seconds=2)

        #VER SE ALGO FOI ENVIADO PARA TRAS
        curr_sent_back_l_free = l_free_nodes[10].get_value()
        ##print(curr_sent_back_l_free)
        if prev_sent_back_l_free and not curr_sent_back_l_free:
            nodeTxt = "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.LT1.piece_O"
            node_initial = client.get_node(f"{nodeTxt}.Initial_Piece")
            node_tool = client.get_node(f"{nodeTxt}.TOOL")
            node_times = client.get_node(f"{nodeTxt}.TIMES")
            node_steps = client.get_node(f"{nodeTxt}.Steps")
            curr_steps = client.get_node(f"{nodeTxt}.Curr_steps")
            p = Pieces(node_initial.get_value(),node_tool.get_value(),node_times.get_value(),node_steps.get_value(),curr_steps.get_value())
            WH1[WH1.index(0)] = p.Initial_Piece
            print("Piece in sent back queue:",p)
            sentBackQueue.append(p)
            print("Sent back queue size",len(sentBackQueue))
        
        prev_sent_back_l_free = curr_sent_back_l_free

        ##if(datetime.now() > end):
            
            ##eod_node.set_value(1,ua.VariantType.Boolean)
            ##time.sleep(5)
            ##end = datetime.now() + timedelta(seconds=60)
            ##eod_node.set_value(0,ua.VariantType.Boolean)


        time.sleep(0.1)


def read_codesys_variables():
    server_url = "opc.tcp://127.0.0.1:4840"
    global client
    client = Client(server_url)
    try:
        client.connect()
        log(f"Connected to OPC UA Server at {server_url}")
        #send_piece_to_codesys(client,"ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UT.piece_I",Pieces(1,[1,2,3,6,0,0],[20,20,45,40],4,3),cell_num=10)
        entry_node = client.get_node(
            "ns=4;s=|var|CODESYS Control Win V3 x64.Application.GVL.Entry_pieces"
        )
        cell_free_nodes = {
            0: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UA.free_O"
            ),
            1: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UB.free_O"
            ),
            2: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UC.free_O"
            ),
            3: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UD.free_O"
            ),
            4: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.U1.free_O"
            ),
            5: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.U2.free_O"
            ),
            6: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.U3.free_O"
            ),
            7: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.U4.free_O"
            ),
            8: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.U5.free_O"
            ),
            9: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.U6.free_O"
            ),
            10: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UT.free_O"
            ),
            11: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UX.free_O"
            ),
            12: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UY.free_O"
            ),
            13: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UZ.free_O"
            ),
            14: client.get_node(
                "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UW.free_O"
            )
        }
        # Adiciona os nós dos tapetes de saída (LA, LB, LC, LCD, L1, L2, L3, L4, L5, L6, LT)
        l_free_nodes = {
            0: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.LA.free_O"),
            1: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.LB.free_O"),
            2: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.LC.free_O"),
            3: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.LCD.free_O"),
            4: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.L1.free_O"),
            5: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.L2.free_O"),
            6: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.L3.free_O"),
            7: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.L4.free_O"),
            8: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.L5.free_O"),
            9: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.L6.free_O"),
            10: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.LT1.free_O"),
        }
        piece_node_prefixes = {
            4: "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.U1.piece_I",
            5: "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.U2.piece_I",
            6: "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.U3.piece_I",
            7: "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.U4.piece_I",
            8: "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.U5.piece_I",
            9: "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.U6.piece_I",
            10: "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UT.piece_I",
            11: "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UX.piece_I",
            12: "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UY.piece_I",
            13: "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UZ.piece_I",
            14: "ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.UW.piece_I",
        }
        end_piece_nodes = {
            4: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.L1.piece_O"),
            5: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.L2.piece_O"),
            6: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.L3.piece_O"),
            7: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.L4.piece_O"),
            8: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.L5.piece_O"),
            9: client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.L6.piece_O")
        }
        beginLines = [
            BeginLine(entry_node, cell_free_nodes[0], 0, piece_type_allowed=1),
            BeginLine(entry_node, cell_free_nodes[1], 1, piece_type_allowed=1),
            BeginLine(entry_node, cell_free_nodes[2], 2, piece_type_allowed=2),
            BeginLine(entry_node, cell_free_nodes[3], 3, piece_type_allowed=2),
        ]
        prodLines = [
            ProdLine(
                cell_num,
                piece_node_prefixes[cell_num],
                cell_free_nodes[cell_num],
                cell_queues,
                end_piece_nodes[cell_num],
                l_free_nodes[cell_num]
            )
            for cell_num in range(4, 10)
        ]
        end_lines = [
            EndLine(entry_node, cell_free_nodes[cell_num], cell_num, piece_node_prefixes[cell_num]) for cell_num in range(11,15)
        ]
        mes_main_loop(beginLines, prodLines, end_lines, cell_free_nodes, l_free_nodes)
    except KeyboardInterrupt:
        log("Interrupted by user. Disconnecting client...")
        client.disconnect()
        log("Client successfully disconnected.")
        sys.exit(0)
    except Exception as e:
        log(f"An error occurred: {e}")
        traceback.print_exc()
        client.disconnect()
        sys.exit(1)
    print("WH1:", WH1)
    print("WH2:", WH2)


if __name__ == "__main__":
    try:
        time.sleep(3)
        read_codesys_variables()
    except KeyboardInterrupt:
        print("MES: Execution interrupted by user (Ctrl+C).")
        sys.exit(0)