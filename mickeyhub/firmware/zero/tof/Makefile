CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra
SOURCES = box_tof.c linux_platform.c vendor/vl53l8cx_api.c
OUTPUT ?= libbox_tof.so

$(OUTPUT): $(SOURCES) vendor/vl53l8cx_api.h vendor/vl53l8cx_buffers.h vendor/platform.h
	$(CC) $(CFLAGS) -std=c11 -fPIC -shared -Ivendor $(SOURCES) -o $@

.PHONY: clean
clean:
	rm -f $(OUTPUT)
