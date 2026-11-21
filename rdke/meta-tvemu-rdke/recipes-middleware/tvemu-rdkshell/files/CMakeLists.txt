cmake_minimum_required(VERSION 3.3)
project(TvemuRDKShell CXX)

find_package(WPEFramework)
find_package(${NAMESPACE}Plugins REQUIRED)
find_package(${NAMESPACE}Definitions REQUIRED)
find_package(CompileSettingsDebug CONFIG REQUIRED)

set(MODULE_NAME ${NAMESPACE}TvemuRDKShell)

add_library(${MODULE_NAME} SHARED RDKShell.cpp Module.cpp)

set_target_properties(${MODULE_NAME} PROPERTIES CXX_STANDARD 11 CXX_STANDARD_REQUIRED YES)

target_link_libraries(${MODULE_NAME} PRIVATE
    CompileSettingsDebug::CompileSettingsDebug
    ${NAMESPACE}Plugins::${NAMESPACE}Plugins
    ${NAMESPACE}Definitions::${NAMESPACE}Definitions)

install(TARGETS ${MODULE_NAME} DESTINATION lib/${STORAGE_DIRECTORY}/plugins)
