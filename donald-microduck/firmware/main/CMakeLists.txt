# WHOLE_ARCHIVE: the tud_descriptor_*_cb definitions in usb_descriptors.c are
# only referenced from libtinyusb, which the linker sees before libmain.
idf_component_register(SRCS "main.c" "usb_descriptors.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES usb esp_driver_gpio esp_driver_pcnt esp_driver_i2s esp_driver_i2c esp_timer esp_hw_support hal soc esp_rom log esp_system
    WHOLE_ARCHIVE)

# espressif/tinyusb ships no tusb_config.h; the component's own sources need
# ours, so put this directory on the library's include path.
idf_build_get_property(build_components BUILD_COMPONENTS)
if(tinyusb IN_LIST build_components)
    set(tinyusb_name tinyusb)
else()
    set(tinyusb_name espressif__tinyusb)
endif()
idf_component_get_property(tusb_lib ${tinyusb_name} COMPONENT_LIB)
target_include_directories(${tusb_lib} PUBLIC "${COMPONENT_DIR}")
