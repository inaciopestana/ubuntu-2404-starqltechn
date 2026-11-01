add_executable(s9-miral-shell
    s9_miral_shell.cpp
)

target_include_directories(s9-miral-shell
    PRIVATE
        ${PROJECT_SOURCE_DIR}/include/client
        ${PROJECT_SOURCE_DIR}/include/server
        ${PROJECT_SOURCE_DIR}/include/platform
)

target_link_libraries(s9-miral-shell
    PRIVATE
        mir1al
        mir1server
)

target_compile_features(s9-miral-shell
    PRIVATE
        cxx_std_17
)

#
# Final deployable binary must not retain paths from the isolated
# ARM64 build environment.
#
set_target_properties(s9-miral-shell PROPERTIES
    SKIP_BUILD_RPATH TRUE
    INSTALL_RPATH ""
)
