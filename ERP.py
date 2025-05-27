import socket
import json
import psycopg2

# Configurações da Base de Dados
conn = psycopg2.connect(
    host="db.fe.up.pt",
    dbname="ii2521",    
    user="ii2521",      
    password="iind25"     
)
cursor = conn.cursor()

# Configurações do Socket UDP
UDP_IP = "0.0.0.0"
UDP_PORT = 5666
BUFFER_SIZE = 65535

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

print(f"[INFO] Servidor UDP à escuta em {UDP_IP}:{UDP_PORT}...\n")

# Loop principal para receber e processar encomendas
while True:
    data, addr = sock.recvfrom(BUFFER_SIZE)
    print(f"[RECEBIDO] Pacote de {addr}")

    try:
        # Converte JSON recebido
        client_order = json.loads(data.decode())

        # Extrai dados do pedido
        name = client_order['name']
        nif = client_order['NIF']
        order_id = client_order['OrderID']

        # Insere na tabela client_orders e obtém o id gerado
        cursor.execute("""
            INSERT INTO orders.client_orders (name, nif, order_id)
            VALUES (%s, %s, %s)
            RETURNING id;
        """, (name, nif, order_id))
        client_order_db_id = cursor.fetchone()[0]

        # Insere os pedidos individuais na tabela orders
        for order in client_order['orders']:
            cursor.execute("""
                INSERT INTO orders.orders (client_order_id, type, quantity, ddate, penalty, status)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (
                client_order_db_id,
                order['type'],
                order['quantity'],
                order['DDate'],
                order['Penalty'],
                "pending"
            ))

        conn.commit()
        print("[OK] Dados inseridos com sucesso.\n")

    except Exception as e:
        print("[ERRO    Q]", e)
