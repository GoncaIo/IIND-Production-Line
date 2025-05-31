import socket
import json
import psycopg2
import threading
import time

# Conexão à base de dados da FEUP
conn = psycopg2.connect(
    host="db.fe.up.pt",
    dbname="ii2521",    
    user="ii2521",      
    password="iind25"     
)
conn.autocommit = True
cursor = conn.cursor()

# Configurações do Socket UDP
UDP_IP = "0.0.0.0"
UDP_PORT = 5666
BUFFER_SIZE = 65535
MAX_PIECES = 24
current_day = 1

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
print(f"[OK] Servidor a escutar em {UDP_IP}:{UDP_PORT}")

def udp_listener():
    while True:
        data, addr = sock.recvfrom(BUFFER_SIZE)
        print(f"[RECEBIDO] Pedido de {addr}")

        try:
            received = json.loads(data.decode())

            # Se for uma lista de pedidos, processa todos
            if isinstance(received, list):
                for client_order in received:
                    process_client_order(client_order)
            else:
                process_client_order(received)

            print("[OK] Pedido(s) inserido(s) com sucesso.\n")

        except Exception as e:
            print("[ERRO] Falha ao processar pedido:", e)

def process_client_order(client_order):
    name = client_order['name']
    nif = client_order['NIF']
    order_id = client_order['OrderID']

    cursor.execute("""
        INSERT INTO orders.client_orders (name, nif, order_id)
        VALUES (%s, %s, %s)
        RETURNING id;
    """, (name, nif, order_id))
    client_order_db_id = cursor.fetchone()[0]

    for order in client_order['orders']:
        cursor.execute("""
            INSERT INTO orders.orders (
                client_order_id, type, quantity, ddate, penalty, status, execution_day
            ) VALUES (%s, %s, %s, %s, %s, %s, %s);
        """, (
            client_order_db_id,
            order['type'],
            order['quantity'],
            order['DDate'],
            order['Penalty'],
            "pending",
            None
        ))

def daily_processor():
    global current_day
    while True:
        # Verifica se existem pedidos na base de dados
        cursor.execute("SELECT COUNT(*) FROM orders.orders WHERE status = 'pending';")
        order_count = cursor.fetchone()[0]

        if order_count == 0:
            print("[INFO] Ainda não há pedidos pendentes. Aguardando...")
            time.sleep(1)
            continue

        print(f"\nNovo dia: {current_day}")

        if current_day != 1:
            # Reduzir o ddate de todos os pedidos pendentes
            cursor.execute("""-
                UPDATE orders.orders
                SET ddate = ddate - 1,
                    status = CASE
                        WHEN ddate - 1 <= 0 THEN 'delayed'
                        ELSE status
                    END
                WHERE ddate > 0;
            """)

        total_today = 0
        ids_to_process = set()

        # Buscar todos os pedidos pendentes
        cursor.execute("""
            SELECT id, quantity, ddate
            FROM orders.orders
            WHERE status = 'pending'
            ORDER BY ddate ASC;
        """)
        pending_orders = cursor.fetchall()

        #Seleciona os que precisam mesmo de ser feitos hoje
        for order_id, quantity, ddate, status in pending_orders:
            if ddate <= 1:
                if total_today + quantity <= MAX_PIECES or status == 'delayed':
                    ids_to_process.add(order_id)
                    total_today += quantity

            else:
                # Estimar se caberá nos próximos dias
                days_remaining = ddate - 1
                cursor.execute("""
                    SELECT SUM(quantity)
                    FROM orders.orders
                    WHERE status = 'pending' AND id != %s AND ddate <= %s;
                """, (order_id, ddate))
                other_qty = cursor.fetchone()[0] or 0

                future_capacity = days_remaining * MAX_PIECES

                if other_qty + quantity > future_capacity:
                    # Se não couber, precisa ser feito hoje
                    if total_today + quantity <= MAX_PIECES:
                        ids_to_process.add(order_id)
                        total_today += quantity

        # 2. Completa o dia com melhores ratios (ddate / quantity)
        remaining_capacity = MAX_PIECES - total_today
        if remaining_capacity > 0:
            cursor.execute("""
                SELECT id, quantity, ddate
                FROM orders.orders
                WHERE status = 'pending' AND id NOT IN %s
                ORDER BY (CAST(ddate AS FLOAT) / quantity) ASC;
            """, (tuple(ids_to_process) if ids_to_process else (0,),))
            remaining_orders = cursor.fetchall()

            for order_id, quantity, ddate in remaining_orders:
                if total_today + quantity <= MAX_PIECES:
                    ids_to_process.add(order_id)
                    total_today += quantity
                else:
                    break

        if ids_to_process:
            cursor.execute("""
                UPDATE orders.orders
                SET status = 'in_progress',
                    execution_day = %s
                WHERE id = ANY(%s);
            """, (current_day, list(ids_to_process)))

        print(f"[INFO] {len(ids_to_process)} pedidos iniciados no dia {current_day}.")
        current_day += 1
        time.sleep(60)  # Simula 1 dia

        
# Iniciar threads
t1 = threading.Thread(target=udp_listener)
t2 = threading.Thread(target=daily_processor)

t1.start()
t2.start()

t1.join()
t2.join()

