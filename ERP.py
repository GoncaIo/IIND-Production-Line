import socket
import json
import psycopg2
import threading
import time

print("[DEBUG] Starting database connection...")
# Database connection to FEUP
conn = psycopg2.connect(
    host="db.fe.up.pt",
    dbname="ii2521",    
    user="ii2521",      
    password="iind25"     
)
conn.autocommit = True
cursor = conn.cursor()
print("[DEBUG] Database connection established.")

# UDP Socket settings
UDP_IP = "0.0.0.0"
UDP_PORT = 5666
BUFFER_SIZE = 65535
MAX_PIECES = 24
current_day = 1

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
print(f"[OK] Server listening on {UDP_IP}:{UDP_PORT}")

def udp_listener():
    print("[DEBUG] UDP listener started.")
    while True:
        data, addr = sock.recvfrom(BUFFER_SIZE)
        print(f"[RECEIVED] Request from {addr}")

        try:
            received = json.loads(data.decode())
            print(f"[DEBUG] Data received: {received}")

             # Defensive: check if received is None
            if received is None:
                print("[ERROR] Received data is None, skipping...")
                continue

            # If it's a list of orders, process all
            if isinstance(received, list):
                for client_order in received:
                    print(f"[DEBUG] Processing order from list: {client_order}")
                    process_client_order(client_order)
            else:
                print(f"[DEBUG] Processing single order: {received}")
                process_client_order(received)

            print("[OK] Order(s) successfully inserted.\n")

        except Exception as e:
            print("[ERROR] Failed to process order:", e)

def process_client_order(client_order):

    print(f"[DEBUG] process_client_order: {client_order}")
    # Defensive: check if client_order is not None and is a dict
    if not client_order or not isinstance(client_order, dict):
        print("[ERROR] client_order is None or not a dict:", client_order)
        return

    # Defensive: check required keys
    required_keys = ['name', 'NIF', 'OrderID', 'orders']
    for key in required_keys:
        if key not in client_order:
            print(f"[ERROR] Missing key '{key}' in client_order: {client_order}")
            return

    name = client_order['name']
    nif = client_order['NIF']
    order_id = client_order['OrderID']

    cursor.execute("""
        INSERT INTO orders.client_orders (name, nif, order_id)
        VALUES (%s, %s, %s)
        RETURNING id;
    """, (name, nif, order_id))
    client_order_db_id = cursor.fetchone()[0]
    print(f"[DEBUG] client_order_db_id: {client_order_db_id}")

    # Defensive: check if 'orders' is a list
    orders = client_order['orders']
    if not isinstance(orders, list):
        print(f"[ERROR] 'orders' field is not a list in client_order: {client_order}")
        return

    for order in orders:
        print(f"[DEBUG] Inserting order: {order}")
        # Defensive: check required order keys
        order_keys = ['type', 'quantity', 'DDate', 'Penalty']
        for k in order_keys:
            if k not in order:
                print(f"[ERROR] Missing key '{k}' in order: {order}")
                continue
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
    print("[DEBUG] daily_processor started.")
    while True:
        # Update ddate for all pending or in_progress orders
        if current_day != 1:
            print(f"[DEBUG] Updating ddate for orders for day {current_day}")
            cursor.execute("""
                UPDATE orders.orders
                SET ddate = ddate - 1
                WHERE status IN ('pending', 'in_progress') AND ddate > 0;
            """)

        # Check if there are pending orders
        cursor.execute("SELECT COUNT(*) FROM orders.orders WHERE status = 'pending';")
        order_count = cursor.fetchone()[0]
        print(f"[DEBUG] Pending orders: {order_count}")

        # While there are no orders in the database, keep waiting for orders
        if order_count == 0 and current_day == 1:
            print("[DEBUG] No pending orders on the first day, waiting...")
            continue

        if order_count == 0:
            print("[INFO] No pending orders. Waiting...")
            print(f"\nNew day: {current_day}")
            current_day += 1
            time.sleep(60)  # Simulate 1 day
            continue
 
        print(f"\nNew day: {current_day}")

        total_today = 0
        ids_to_process = set()

        # Fetch all pending orders
        cursor.execute("""
            SELECT id, quantity, ddate
            FROM orders.orders
            WHERE status = 'pending'
            ORDER BY ddate ASC;
        """)
        pending_orders = cursor.fetchall()
        print(f"[DEBUG] Pending orders fetched: {pending_orders}")

        # Select those that must be done today
        for order_id, quantity, ddate in pending_orders:
            print(f"[DEBUG] Evaluating order {order_id} (qty={quantity}, ddate={ddate})")
            if ddate <= 1:
                if total_today + quantity <= MAX_PIECES:
                    ids_to_process.add(order_id)
                    total_today += quantity
                    print(f"[DEBUG] Order {order_id} added for today (ddate<=1)")
            else:
                # Estimate if it will fit in the next days
                days_remaining = ddate - 1
                cursor.execute("""
                    SELECT SUM(quantity)
                    FROM orders.orders
                    WHERE status = 'pending' AND id != %s AND ddate <= %s;
                """, (order_id, ddate))
                other_qty = cursor.fetchone()[0] or 0

                future_capacity = days_remaining * MAX_PIECES

                print(f"[DEBUG] Order {order_id}: other_qty={other_qty}, future_capacity={future_capacity}")
                if other_qty + quantity > future_capacity:
                    # If it won't fit, must be done today
                    if total_today + quantity <= MAX_PIECES:
                        ids_to_process.add(order_id)
                        total_today += quantity
                        print(f"[DEBUG] Order {order_id} forced for today (won't fit in future)")

        # 2. Fill the day with best ratios (ddate / quantity)
        remaining_capacity = MAX_PIECES - total_today
        print(f"[DEBUG] Remaining capacity for today: {remaining_capacity}")
        if remaining_capacity > 0:
            cursor.execute("""
                SELECT id, quantity, ddate
                FROM orders.orders
                WHERE status = 'pending' AND id NOT IN %s
                ORDER BY (CAST(ddate AS FLOAT) / quantity) ASC;
            """, (tuple(ids_to_process) if ids_to_process else (0,),))
            remaining_orders = cursor.fetchall()
            print(f"[DEBUG] Remaining orders to fill the day: {remaining_orders}")

            for order_id, quantity, ddate in remaining_orders:
                if total_today + quantity <= MAX_PIECES:
                    ids_to_process.add(order_id)
                    total_today += quantity
                    print(f"[DEBUG] Order {order_id} added to fill the day")
                else:
                    break

        if ids_to_process:
            print(f"[DEBUG] Updating orders' status to 'in_progress': {ids_to_process}")
            cursor.execute("""
                UPDATE orders.orders
                SET status = 'in_progress',
                    execution_day = %s
                WHERE id = ANY(%s);
            """, (current_day, list(ids_to_process)))

        print(f"[INFO] {len(ids_to_process)} orders started on day {current_day}.")
        current_day += 1
        time.sleep(60)  # Simulate 1 day

        
if __name__ == "__main__":
    try:
        t1 = threading.Thread(target=udp_listener)
        t2 = threading.Thread(target=daily_processor)

        t1.start()
        t2.start()

        t1.join()
        t2.join()
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down server...")    
        sock.close()
        cursor.close()
        conn.close()
        # Threads will be closed when the program exits