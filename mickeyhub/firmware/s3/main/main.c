#include "power.h"
#include "pins.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "driver/i2c_master.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

static const unsigned tx_pins[3] = S3_RADAR_TX_VALUES;
static const unsigned rx_pins[3] = S3_RADAR_RX_VALUES;
static const uart_port_t ports[3] = {UART_NUM_0, UART_NUM_1, UART_NUM_2};
static bool tx_enabled;
static uint32_t now_ms(void) { return (uint32_t)(esp_timer_get_time() / 1000); }
static bool set_uart_outputs(bool enabled) {
    if (enabled == tx_enabled) return true;
    for (unsigned i = 0; i < 3; ++i) {
        if (enabled) {
            if (uart_set_pin(ports[i], tx_pins[i], rx_pins[i],
                             UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE) != ESP_OK) return false;
        } else {
            uart_wait_tx_done(ports[i], pdMS_TO_TICKS(50));
            gpio_reset_pin(tx_pins[i]);
            gpio_set_direction(tx_pins[i], GPIO_MODE_INPUT);
            gpio_set_pull_mode(tx_pins[i], GPIO_FLOATING);
        }
        gpio_set_pull_mode(rx_pins[i], GPIO_FLOATING);
    }
    tx_enabled = enabled; return true;
}
void app_main(void) {
    /* ROM logs used GPIO43/44; leave those unused breakouts quiet afterward. */
    gpio_reset_pin(43); gpio_set_direction(43, GPIO_MODE_INPUT);
    gpio_set_pull_mode(43, GPIO_FLOATING);
    gpio_reset_pin(44); gpio_set_direction(44, GPIO_MODE_INPUT);
    gpio_set_pull_mode(44, GPIO_FLOATING);
    gpio_config_t relay = {.pin_bit_mask = 1ULL << S3_RADAR_RELAY,
                          .mode = GPIO_MODE_OUTPUT_OD, .pull_up_en = GPIO_PULLUP_DISABLE,
                          .pull_down_en = GPIO_PULLDOWN_DISABLE, .intr_type = GPIO_INTR_DISABLE};
    gpio_set_level(S3_RADAR_RELAY, 1); ESP_ERROR_CHECK(gpio_config(&relay));
    gpio_set_level(S3_RADAR_RELAY, 1);
    uart_config_t config = {.baud_rate = BOX_RADAR_BAUD, .data_bits = UART_DATA_8_BITS,
                           .parity = UART_PARITY_DISABLE, .stop_bits = UART_STOP_BITS_1,
                           .flow_ctrl = UART_HW_FLOWCTRL_DISABLE, .source_clk = UART_SCLK_DEFAULT};
    for (unsigned i = 0; i < 3; ++i) {
        ESP_ERROR_CHECK(uart_driver_install(ports[i], 1024, 0, 0, NULL, 0));
        ESP_ERROR_CHECK(uart_param_config(ports[i], &config));
        ESP_ERROR_CHECK(uart_set_pin(ports[i], UART_PIN_NO_CHANGE, rx_pins[i],
                                    UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
        gpio_reset_pin(tx_pins[i]); gpio_set_direction(tx_pins[i], GPIO_MODE_INPUT);
        gpio_set_pull_mode(tx_pins[i], GPIO_FLOATING);
        gpio_set_pull_mode(rx_pins[i], GPIO_FLOATING);
    }
    i2c_master_bus_config_t bus_config = {
        .i2c_port = I2C_NUM_0, .sda_io_num = S3_I2C_SDA, .scl_io_num = S3_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = false};
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_config, &bus));
    i2c_device_config_t device_config = {.dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = BOX_I2C_ADDRESS, .scl_speed_hz = 100000};
    i2c_master_dev_handle_t peer;
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &device_config, &peer));
    box_s3 state; box_s3_init(&state, esp_random());
    box_radar_parser parsers[3] = {0};
    uint8_t latest[3][30] = {{0}}; bool pending[3] = {false};
    uint16_t counts[3] = {0}, sequence = 0; unsigned next_sensor = 0;
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        for (unsigned i = 0; i < 3; ++i) {
            uint8_t bytes[128], sample[30];
            int count = uart_read_bytes(ports[i], bytes, sizeof(bytes), 0);
            for (int n = 0; n < count; ++n) {
                if (box_radar_byte(&parsers[i], bytes[n], sample) && tx_enabled) {
                    memcpy(latest[i], sample, 30); pending[i] = true; ++counts[i];
                }
            }
            if (!tx_enabled) pending[i] = false;
        }
        box_s3_tick(&state, now_ms(), !tx_enabled);
        if (!set_uart_outputs(state.tx_enabled)) {
            state.tx_enabled = false;
            /* Force every output to high-Z if a peripheral remap failed. */
            tx_enabled = true; set_uart_outputs(false);
            state.faults |= BOX_FAULT_LINK; state.phase = BOX_LINK_FAULT;
        }
        gpio_set_level(S3_RADAR_RELAY, state.relay_on ? 0 : 1);
        box_packet outgoing = box_s3_report(&state, ++sequence, !tx_enabled);
        int sample_index = -1;
        for (unsigned n = 0; n < 3; ++n) {
            unsigned i = (next_sensor + n) % 3;
            if (pending[i]) {
                sample_index = (int)i; outgoing.length = 48; outgoing.payload[3] = (uint8_t)i;
                memcpy(outgoing.payload + 16, latest[i], 30);
                outgoing.payload[46] = (uint8_t)counts[i];
                outgoing.payload[47] = (uint8_t)(counts[i] >> 8);
                next_sensor = (i + 1) % 3; break;
            }
        }
        uint8_t tx[64], rx[64]; box_packet incoming;
        box_encode(&outgoing, tx);
        esp_err_t result = i2c_master_transmit_receive(peer, tx, sizeof(tx), rx, sizeof(rx), 40);
        if (result == ESP_OK) {
            if (box_decode(rx, &incoming)) box_s3_receive(&state, &incoming, now_ms());
            if (sample_index >= 0) pending[sample_index] = false;
        }
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(20));
    }
}
