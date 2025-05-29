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
MAX_PIECES = 20
current_day = 0

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
print(f"[OK] Servidor a escutar em {UDP_IP}:{UDP_PORT}")

def udp_listener():
    while True:
        data, addr = sock.recvfrom(BUFFER_SIZE)
        print(f"[RECEBIDO] Pedido de {addr}")

        try:
            client_order = json.loads(data.decode())

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

            print("[OK] Pedido inserido com sucesso.\n")

        except Exception as e:
            print("[ERRO] Falha ao processar pedido:", e)

def daily_processor():
    global current_day
    while True:
        current_day += 1
        print(f"\n Novo dia: {current_day}")

        # Obter pedidos pendentes ordenados por (ddate / quantidade)
        cursor.execute("""
            SELECT id, quantity, ddate FROM orders.orders
            WHERE status = 'pending'
            ORDER BY (CAST(ddate AS FLOAT) / quantity) ASC
        """)
        rows = cursor.fetchall()

        total = 0
        ids_to_process = []

        for row in rows:
            order_id, qty, ddate = row
            if total + qty <= MAX_PIECES:
                ids_to_process.append(order_id)
                total += qty
            else:
                break

        if ids_to_process:
            cursor.execute("""
                UPDATE orders.orders
                SET status = 'in_progress',
                    execution_day = %s
                WHERE id = ANY(%s)
            """, (current_day, ids_to_process))

        # Reduzir o ddate de todos os pedidos pendentes
        cursor.execute("""
            UPDATE orders.orders
            SET ddate = ddate - 1,
                status = CASE
                    WHEN ddate - 1 <= 0 THEN 'delayed'
                    ELSE status
                END
            WHERE status = 'pending';
        """)

        print(f"[INFO] {len(ids_to_process)} pedidos iniciados no dia {current_day}.")
        time.sleep(57)  # Simula 1 dia
        
# Iniciar threads
t1 = threading.Thread(target=udp_listener)
t2 = threading.Thread(target=daily_processor)

t1.start()
t2.start()

t1.join()
t2.join()
