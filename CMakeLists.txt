cmake_minimum_required(VERSION 3.10)
project(MES_OPC_UA)

set(CMAKE_CXX_STANDARD 11)

# Adicione o caminho para os ficheiros da biblioteca open62541
include_directories(path/to/open62541/include)
link_directories(path/to/open62541/lib)

add_executable(MES_OPC_UA MES-OPC-UA_PublishSubscribe.cpp)

# Ligar a biblioteca open62541
target_link_libraries(MES_OPC_UA open62541)