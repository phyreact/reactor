#pragma once
#include "protocol.h"

enum box_phase { BOX_OFF, BOX_WAIT_RELEASE, BOX_STARTING, BOX_RUNNING,
                 BOX_STOPPING, BOX_LINK_FAULT };
enum box_fault { BOX_FAULT_LINK = 1, BOX_FAULT_PEER_RESTART = 2,
                 BOX_FAULT_SHUTDOWN_TIMEOUT = 4 };
enum box_shutdown { BOX_SHUTDOWN_NONE, BOX_SHUTDOWN_HOST, BOX_SHUTDOWN_ALL };
typedef struct {
    uint32_t boot, peer_boot, last_peer_ms, cycle, phase_since, faults;
    uint16_t peer_sequence;
    bool peer_seen, requested_on, peer_released, relay_on, tx_enabled;
    bool relay_switched;
    uint32_t relay_changed_ms;
    enum box_phase phase;
} box_s3;
typedef struct {
    uint32_t boot, peer_boot, last_peer_ms, cycle, faults;
    uint32_t shutdown_token, shutdown_counter, shutdown_since, safe_since;
    uint16_t peer_sequence;
    bool peer_seen, desired_radar, tx_enabled, main_hold, host_on, host_ready, tof_on;
    bool safe_received, peer_relay;
    bool host_switched, tof_switched, main_release_armed;
    uint32_t host_changed_ms, tof_changed_ms, main_release_since;
    uint32_t peer_cycle;
    enum box_phase peer_phase;
    enum box_shutdown shutdown;
    bool button_initialized, button_raw_down, button_stable_down;
    bool startup_pending, startup_pressed, button_armed, button_long_sent;
    uint32_t button_changed_ms, button_pressed_ms, startup_since;
} box_rp;
void box_s3_init(box_s3 *s, uint32_t boot);
bool box_s3_receive(box_s3 *s, const box_packet *p, uint32_t now);
void box_s3_tick(box_s3 *s, uint32_t now, bool local_tx_released);
box_packet box_s3_report(const box_s3 *s, uint16_t sequence, bool local_tx_released);
void box_rp_init(box_rp *r, uint32_t boot);
void box_rp_button_init(box_rp *r, bool down, uint32_t now);
void box_rp_button(box_rp *r, bool down, uint32_t now);
bool box_rp_receive(box_rp *r, const box_packet *p, uint32_t now);
void box_rp_tick(box_rp *r, uint32_t now);
bool box_rp_command(box_rp *r, enum box_command command, uint32_t value, uint32_t now);
box_packet box_rp_request(const box_rp *r, uint16_t sequence, bool local_tx_released);
box_packet box_rp_report(const box_rp *r, uint16_t sequence, bool local_tx_released);
