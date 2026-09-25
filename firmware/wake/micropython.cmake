add_library(usermod_wake INTERFACE)
target_sources(usermod_wake INTERFACE ${CMAKE_CURRENT_LIST_DIR}/wake.c)
target_include_directories(usermod_wake INTERFACE ${CMAKE_CURRENT_LIST_DIR})
target_link_libraries(usermod INTERFACE usermod_wake)
