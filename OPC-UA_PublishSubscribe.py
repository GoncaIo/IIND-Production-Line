from opcua import Client
from opcua import ua
import time
import sys


# Note: THIS CODE IS PURELY DEMONSTRATIVE AND YOU WILL NEED TO MAKE CHANGES IN ORDER TO APPLY IT FOR YOUR PROJECT
def read_codesys_variables():
    # Replace with your actual server URL
    server_url = "opc.tcp://127.0.0.1:4840"
    
    client = Client(server_url)

    # Connect to server
    client.connect()
    print(f"Connected to OPC UA Server at {server_url}")
    
    try:
        while True:
            
            # Access the nodes using their NodeId, namely the nodes which we will want to read from CODESYS
            # The names withing get_node() will depend on the configuration for each user, so change it at will.
            Warehouse1 = client.get_node("ns=4;s=|var|CODESYS Control Win V3 x64.Application.PLC_PRG.int1")
        
            # Read the values from the server
            print(f"NUM_PIECES_WAREHOUSE1: {Warehouse1.get_value()}")
            
            # Get the data types from the server
            dv1 = Warehouse1.get_data_value()
            
            # Print data types to help troubleshoot
            print(f"Warehouse1 data type: {dv1.Value.VariantType}")
            
            time.sleep(1)  # Adjust the sleep time as needed

            # Example of setting values (if needed) to CODESYS variables
            Warehouse1.set_value(ua.Variant(Warehouse1.get_value() + 1, ua.VariantType.Int16)) # Example of setting a value

    except KeyboardInterrupt:
        # Close the server before exiting
        print("\nStopping client...")
        client.disconnect()
        print("Client stopped")
        sys.exit(0)
    
    except Exception as e:
        print(f"An error occurred: {e}")
        client.disconnect()
        sys.exit(1)

if __name__ == "__main__":
    values = read_codesys_variables()
