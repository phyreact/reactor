#include "power.h"
#include "pins.h"
#include "pico/stdlib.h"
#include "pico/rand.h"
#include "pico/i2c_slave.h"
#include "hardware/irq.h"
#include "hardware/sync.h"
#include "hardware/uart.h"
#include <string.h>

typedef struct { uint8_t data[512]; volatile uint16_t read, write; volatile uint32_t drops; } ring;
static ring host_rx, radar_rx;
static uint8_t tx_latest[64], tx_active[64], rx_work[64], rx_latest[64];
static volatile bool rx_ready;
static size_t rx_used, tx_used;
static box_rp state;
static bool radar_enabled, host_sequence_seen;
static uint16_t host_sequence, output_sequence, link_sequence;
static uint8_t last_command_ok;
static uint32_t now_ms(void) { return to_ms_since_boot(get_absolute_time()); }
static void ring_irq(ring *r, uart_inst_t *uart) {
    while (uart_is_readable(uart)) {
        uint8_t byte = (uint8_t)uart_getc(uart);
        uint16_t next = (r->write + 1u) & 511u;
        if (next == r->read) { ++r->drops; continue; }
        r->data[r->write] = byte; r->write = next;
    }
}
static bool ring_pop(ring *r, uint8_t *byte) {
    if (r->read == r->write) return false;
    *byte = r->data[r->read]; r->read = (r->read + 1u) & 511u; return true;
}
static void host_irq(void) { ring_irq(&host_rx, uart0); }
static void radar_irq(void) { ring_irq(&radar_rx, uart1); }
static void relay_init(unsigned pin, bool on) {
    gpio_init(pin); gpio_disable_pulls(pin); gpio_put(pin, 0); gpio_set_dir(pin, on);
}
static void relay_set(unsigned pin, bool on) {
    /* LOW-active original module: drive LOW to energize, high-Z to release. */
    gpio_put(pin, 0); gpio_set_dir(pin, on);
}
static void radar_tx_set(bool enabled) {
    if (enabled == radar_enabled) return;
    if (enabled) {
        gpio_set_function(RP_RADAR_TX, GPIO_FUNC_UART);
    } else {
        uart_tx_wait_blocking(uart1); /* No CTS; bounded by the hardware TX FIFO. */
        gpio_set_function(RP_RADAR_TX, GPIO_FUNC_SIO);
        gpio_set_dir(RP_RADAR_TX, GPIO_IN); gpio_disable_pulls(RP_RADAR_TX);
    }
    radar_enabled = enabled;
}
static void i2c_event(i2c_inst_t *i2c, i2c_slave_event_t event) {
    switch (event) {
    case I2C_SLAVE_RECEIVE: {
        uint8_t byte = i2c_read_byte_raw(i2c);
        if (rx_used < sizeof(rx_work)) rx_work[rx_used] = byte;
        if (rx_used <= sizeof(rx_work)) ++rx_used;
        break;
    }
    case I2C_SLAVE_REQUEST:
        if (!tx_used) memcpy(tx_active, tx_latest, sizeof(tx_active));
        i2c_write_byte_raw(i2c, tx_used < sizeof(tx_active) ? tx_active[tx_used++] : 0);
        break;
    case I2C_SLAVE_FINISH:
        if (rx_used == sizeof(rx_work)) {
            memcpy(rx_latest, rx_work, sizeof(rx_latest)); rx_ready = true;
        }
        rx_used = 0; tx_used = 0; break;
    }
}
static void publish_link(void) {
    box_packet p = box_rp_request(&state, ++link_sequence, !radar_enabled);
    uint8_t bytes[64]; box_encode(&p, bytes);
    uint32_t interrupts = save_and_disable_interrupts();
    memcpy(tx_latest, bytes, 64);
    restore_interrupts(interrupts);
}
static void send_host(box_packet *p) {
    uint8_t bytes[64]; p->sequence = ++output_sequence; box_encode(p, bytes);
    uart_write_blocking(uart0, bytes, sizeof(bytes));
}
static void send_status(void) {
    box_packet p = box_rp_report(&state, 0, !radar_enabled);
    p.length = 24; p.payload[20] = (uint8_t)host_sequence;
    p.payload[21] = (uint8_t)(host_sequence >> 8);
    p.payload[22] = host_sequence_seen; p.payload[23] = last_command_ok;
    send_host(&p);
}
static void send_radar(unsigned index, uint16_t count, const uint8_t *sample) {
    box_packet p = {.type = BOX_RADAR_SAMPLE, .length = 37, .boot = state.boot};
    p.payload[0] = (uint8_t)index; box_put32(p.payload + 1, now_ms());
    p.payload[5] = (uint8_t)count; p.payload[6] = (uint8_t)(count >> 8);
    memcpy(p.payload + 7, sample, 30); send_host(&p);
}
static void setup_uart(uart_inst_t *uart, unsigned baud, unsigned tx, unsigned rx,
                       unsigned irq, irq_handler_t handler, bool enable_tx) {
    uart_init(uart, baud); uart_set_hw_flow(uart, false, false);
    uart_set_format(uart, 8, 1, UART_PARITY_NONE);
    gpio_set_function(rx, GPIO_FUNC_UART); gpio_disable_pulls(rx);
    if (enable_tx) gpio_set_function(tx, GPIO_FUNC_UART);
    else { gpio_init(tx); gpio_set_dir(tx, GPIO_IN); gpio_disable_pulls(tx); }
    irq_set_exclusive_handler(irq, handler); irq_set_enabled(irq, true);
    uart_set_irq_enables(uart, true, false);
}
int main(void) {
    /* Rear DPDT pole A momentarily closes J51's UPS switch loop. M16 keeps
       that loop closed after the press; assert it before slow initialization.
       Pole B is an isolated RP_BUTTON-to-GND contact, never tied to pole A. */
    relay_init(RP_MAIN_HOLD, true);
    relay_init(RP_HOST_RELAY, false); relay_init(RP_TOF_RELAY, false);
    box_rp_init(&state, get_rand_32());
    gpio_init(RP_BUTTON); gpio_set_dir(RP_BUTTON, GPIO_IN); gpio_pull_up(RP_BUTTON);
    box_rp_button_init(&state, !gpio_get(RP_BUTTON), now_ms());
    setup_uart(uart0, BOX_ZERO_BAUD, RP_ZERO_TX, RP_ZERO_RX, UART0_IRQ, host_irq, true);
    setup_uart(uart1, BOX_RADAR_BAUD, RP_RADAR_TX, RP_RADAR_RX, UART1_IRQ, radar_irq, false);
    gpio_set_function(RP_I2C_SDA, GPIO_FUNC_I2C); gpio_disable_pulls(RP_I2C_SDA);
    gpio_set_function(RP_I2C_SCL, GPIO_FUNC_I2C); gpio_disable_pulls(RP_I2C_SCL);
    i2c_init(i2c1, 100000); publish_link();
    i2c_slave_init(i2c1, BOX_I2C_ADDRESS, i2c_event);
    box_stream commands = {0}; box_radar_parser radar = {0};
    uint16_t samples[4] = {0}; bool sample_seen[3] = {0};
    uint32_t last_status = 0, last_publish = 0;
    uint32_t old_session = state.boot;
    while (true) {
        uint32_t now = now_ms();
        uint8_t bytes[64]; bool ready;
        uint32_t interrupts = save_and_disable_interrupts();
        ready = rx_ready;
        if (ready) { memcpy(bytes, rx_latest, sizeof(bytes)); rx_ready = false; }
        restore_interrupts(interrupts);
        box_packet p;
        if (ready && box_decode(bytes, &p) && box_rp_receive(&state, &p, now)) {
            if (p.length >= 48 && p.payload[3] < 3 &&
                p.payload[0] == BOX_RUNNING && box_get32(p.payload + 4) == state.cycle) {
                unsigned i = p.payload[3];
                uint16_t count = (uint16_t)p.payload[46] | (uint16_t)p.payload[47] << 8;
                if (!sample_seen[i] || count != samples[i]) {
                    sample_seen[i] = true; samples[i] = count;
                    send_radar(i, count, p.payload + 16);
                }
            }
        }
        uint8_t byte, sample[30];
        while (ring_pop(&host_rx, &byte)) {
            if (!box_stream_byte(&commands, byte, &p)) continue;
            if (p.type != BOX_HOST_COMMAND || p.length != 5 || p.boot != state.boot ||
                (host_sequence_seen && !box_sequence_newer(p.sequence, host_sequence))) continue;
            host_sequence = p.sequence; host_sequence_seen = true;
            last_command_ok = box_rp_command(&state, (enum box_command)p.payload[0],
                                            box_get32(p.payload + 1), now);
            send_status();
        }
        while (ring_pop(&radar_rx, &byte)) {
            if (box_radar_byte(&radar, byte, sample) && radar_enabled)
                send_radar(3, ++samples[3], sample);
        }
        box_rp_button(&state, !gpio_get(RP_BUTTON), now);
        box_rp_tick(&state, now);
        radar_tx_set(state.tx_enabled);
        relay_set(RP_TOF_RELAY, state.tof_on);
        relay_set(RP_HOST_RELAY, state.host_on);
        relay_set(RP_MAIN_HOLD, state.main_hold);
        if (old_session != state.boot) {
            old_session = state.boot; host_sequence_seen = false;
        }
        if ((uint32_t)(now - last_publish) >= 20) { publish_link(); last_publish = now; }
        if ((uint32_t)(now - last_status) >= 200) { send_status(); last_status = now; }
        sleep_ms(1);
    }
}
