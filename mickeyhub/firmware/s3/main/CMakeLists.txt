idf_component_register(SRCS "main.c" "../../common/power.c" "../../common/protocol.c"
                       INCLUDE_DIRS "../../common"
                       REQUIRES esp_driver_uart esp_driver_i2c esp_driver_gpio
                                esp_timer esp_system)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
