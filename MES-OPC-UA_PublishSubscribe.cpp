#include <iostream>
#include <string>
#include <thread>
#include <chrono>
#include <signal.h>
#include <open62541/client_config_default.h>
#include <open62541/client_highlevel.h>
#include <open62541/plugin/log_stdout.h>

volatile bool running = true;

// Signal handler for graceful shutdown
void signalHandler(int signum) {
    std::cout << "Interrupt signal (" << signum << ") received.\n";
    running = false;
}

int main() {
    // Register signal handler for graceful shutdown
    signal(SIGINT, signalHandler);
    
    // Create a client
    UA_Client *client = UA_Client_new();
    UA_ClientConfig_setDefault(UA_Client_getConfig(client));
    
    // Server endpoint URL - using 127.0.0.1 since it worked
    const char* serverUrl = "opc.tcp://127.0.0.1:4840";
    
    // Connect to the server
    std::cout << "Attempting to connect to: " << serverUrl << std::endl;
    UA_StatusCode retval = UA_Client_connect(client, serverUrl);

    if (retval != UA_STATUSCODE_GOOD) {
        std::cerr << "Failed to connect to server. Status code: " << retval << std::endl;
        UA_Client_delete(client);
        return EXIT_FAILURE;
    }
    
    std::cout << "Connected to OPC UA Server at " << serverUrl << std::endl;

    try {
        // Define the node ids for our variables (same as in Python code)
        UA_NodeId warehouse1NodeId = UA_NODEID_STRING(4, const_cast<char*>("|var|CODESYS Control Win V3 x64.Application.GVL.NUM_PIECES_WAREHOUSE1"));
        UA_NodeId warehouse2NodeId = UA_NODEID_STRING(4, const_cast<char*>("|var|CODESYS Control Win V3 x64.Application.GVL.NUM_PIECES_WAREHOUSE2"));
        UA_NodeId warehouseOutNodeId = UA_NODEID_STRING(4, const_cast<char*>("|var|CODESYS Control Win V3 x64.Application.GVL.WAREHOUSE_OUT_1"));
        while (running) {
            // Variables to store the values
            UA_Int16 value1 = 0;
            UA_Int16 value2 = 0;
            UA_UInt16 value3 = 0;
            
            // Initialize variant for reading
            UA_Variant variant;
            UA_Variant_init(&variant);
            
            // Read Warehouse1
            retval = UA_Client_readValueAttribute(client, warehouse1NodeId, &variant);
            if (retval == UA_STATUSCODE_GOOD && UA_Variant_hasScalarType(&variant, &UA_TYPES[UA_TYPES_INT16])) {
                value1 = *(UA_Int16*)variant.data;
                std::cout << "NUM_PIECES_WAREHOUSE1: " << value1 << std::endl;
                std::cout << "Warehouse1 data type: Int16" << std::endl;
            } else {
                std::cerr << "Error reading Warehouse1: " << retval << std::endl;
            }
            UA_Variant_clear(&variant);
            
            // Read Warehouse2
            retval = UA_Client_readValueAttribute(client, warehouse2NodeId, &variant);
            if (retval == UA_STATUSCODE_GOOD && UA_Variant_hasScalarType(&variant, &UA_TYPES[UA_TYPES_INT16])) {
                value2 = *(UA_Int16*)variant.data;
                std::cout << "NUM_PIECES_WAREHOUSE2: " << value2 << std::endl;
                std::cout << "Warehouse2 data type: Int16" << std::endl;
            } else {
                std::cerr << "Error reading Warehouse2: " << retval << std::endl;
            }
            UA_Variant_clear(&variant);
            
            // Read WarehouseOut
            retval = UA_Client_readValueAttribute(client, warehouseOutNodeId, &variant);
            if (retval == UA_STATUSCODE_GOOD && UA_Variant_hasScalarType(&variant, &UA_TYPES[UA_TYPES_UINT16])) {
                value3 = *(UA_UInt16*)variant.data;
                std::cout << "WAREHOUSE_OUT_1: " << value3 << std::endl;
                std::cout << "WarehouseOut data type: UInt16" << std::endl;
            } else {
                std::cerr << "Error reading WarehouseOut: " << retval << std::endl;
            }
            UA_Variant_clear(&variant);
            
            std::cout << std::endl;
            
            // Wait for 1 second
            std::this_thread::sleep_for(std::chrono::seconds(1));
            
            // Set new values
            // For Warehouse1
            UA_Int16 newValue1 = value1 + 1;
            UA_Variant_init(&variant);
            UA_Variant_setScalar(&variant, &newValue1, &UA_TYPES[UA_TYPES_INT16]);
            retval = UA_Client_writeValueAttribute(client, warehouse1NodeId, &variant);
            if (retval != UA_STATUSCODE_GOOD) {
                std::cerr << "Error writing Warehouse1: " << retval << std::endl;
            }
            
            // For Warehouse2
            UA_Int16 newValue2 = value1 + 1;  // Using value1 like in Python
            UA_Variant_setScalar(&variant, &newValue2, &UA_TYPES[UA_TYPES_INT16]);
            retval = UA_Client_writeValueAttribute(client, warehouse2NodeId, &variant);
            if (retval != UA_STATUSCODE_GOOD) {
                std::cerr << "Error writing Warehouse2: " << retval << std::endl;
            }
            
            // For WarehouseOut
            UA_UInt16 newValue3 = value1 + 1;  // Using value1 like in Python
            UA_Variant_setScalar(&variant, &newValue3, &UA_TYPES[UA_TYPES_UINT16]);
            retval = UA_Client_writeValueAttribute(client, warehouseOutNodeId, &variant);
            if (retval != UA_STATUSCODE_GOOD) {
                std::cerr << "Error writing WarehouseOut: " << retval << std::endl;
            }
        }
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
    }
    
    // Disconnect and cleanup
    std::cout << "\nStopping client..." << std::endl;
    UA_Client_disconnect(client);
    UA_Client_delete(client);
    std::cout << "Client stopped" << std::endl;
    
    return EXIT_SUCCESS;
}
