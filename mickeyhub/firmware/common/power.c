#include "power.h"
#include <string.h>

static bool elapsed(uint32_t now, uint32_t since, uint32_t limit) {
    return (uint32_t)(now - since) >= limit;
}
static bool fresh_rp(const box_rp *r, uint32_t now) {
    return r->peer_seen && !elapsed(now, r->last_peer_ms, BOX_LINK_TIMEOUT_MS);
}
void box_s3_init(box_s3 *s, uint32_t boot) {
    memset(s, 0, sizeof(*s)); s->boot = boot ? boot : 1;
}
bool box_s3_receive(box_s3 *s, const box_packet *p, uint32_t now) {
    if (p->type != BOX_RP_LINK || p->length < 8 || !p->boot) return false;
    bool restart = s->peer_seen && p->boot != s->peer_boot;
    if (s->peer_seen && !restart && !box_sequence_newer(p->sequence, s->peer_sequence))
        return false;
    uint32_t cycle = box_get32(p->payload + 4);
    bool new_cycle = !s->peer_seen || restart || cycle != s->cycle;
    if (restart) s->faults |= BOX_FAULT_PEER_RESTART;
    s->peer_boot = p->boot; s->peer_sequence = p->sequence;
    s->peer_seen = true; s->last_peer_ms = now;
    s->requested_on = p->payload[0] != 0;
    s->peer_released = p->payload[1] != 0;
    if (new_cycle || (s->phase == BOX_LINK_FAULT && !s->requested_on)) {
        s->cycle = cycle; s->phase = BOX_WAIT_RELEASE; s->tx_enabled = false;
        s->faults &= ~BOX_FAULT_LINK;
    }
    return true;
}
void box_s3_tick(box_s3 *s, uint32_t now, bool released) {
    if (!s->peer_seen) return;
    if (elapsed(now, s->last_peer_ms, BOX_LINK_TIMEOUT_MS)) {
        s->faults |= BOX_FAULT_LINK; s->tx_enabled = false;
        s->phase = BOX_LINK_FAULT;
        /* Never cut a live sensor rail merely because communication timed out. */
        return;
    }
    if (s->phase == BOX_WAIT_RELEASE && released && s->peer_released) {
        if (s->relay_on != s->requested_on) {
            if (s->relay_switched &&
                !elapsed(now, s->relay_changed_ms, BOX_RELAY_MIN_DWELL_MS)) return;
            s->relay_switched = true; s->relay_changed_ms = now;
        }
        s->relay_on = s->requested_on; s->phase_since = now;
        s->phase = s->requested_on ? BOX_STARTING : BOX_STOPPING;
    }
    if (s->phase == BOX_STARTING && elapsed(now, s->phase_since, BOX_RADAR_ON_SETTLE_MS)) {
        s->phase = BOX_RUNNING; s->tx_enabled = true;
    }
    if (s->phase == BOX_STOPPING && elapsed(now, s->phase_since, BOX_RADAR_OFF_SETTLE_MS))
        s->phase = BOX_OFF;
}
box_packet box_s3_report(const box_s3 *s, uint16_t seq, bool released) {
    box_packet p = {.type = BOX_S3_LINK, .length = 16, .sequence = seq, .boot = s->boot};
    p.payload[0] = (uint8_t)s->phase; p.payload[1] = s->relay_on;
    p.payload[2] = released; p.payload[3] = 0xff;
    box_put32(p.payload + 4, s->cycle); box_put32(p.payload + 8, s->peer_boot);
    box_put32(p.payload + 12, s->faults); return p;
}
void box_rp_init(box_rp *r, uint32_t boot) {
    memset(r, 0, sizeof(*r)); r->boot = boot ? boot : 1; r->main_hold = true;
}
static void radar_request(box_rp *r, bool on) {
    r->desired_radar = on; r->tx_enabled = false; ++r->cycle;
}
static bool tof_set(box_rp *r, bool on, uint32_t now) {
    if (r->tof_on == on) return true;
    if (r->tof_switched && !elapsed(now, r->tof_changed_ms, BOX_RELAY_MIN_DWELL_MS))
        return false;
    r->tof_on = on; r->tof_switched = true; r->tof_changed_ms = now;
    return true;
}
bool box_rp_receive(box_rp *r, const box_packet *p, uint32_t now) {
    if (p->type != BOX_S3_LINK || p->length < 16 || !p->boot ||
        box_get32(p->payload + 8) != r->boot ||
        p->payload[0] > BOX_LINK_FAULT) return false;
    bool restart = r->peer_seen && r->peer_boot != p->boot;
    if (r->peer_seen && !restart && !box_sequence_newer(p->sequence, r->peer_sequence))
        return false;
    if (restart) {
        r->faults |= BOX_FAULT_PEER_RESTART; radar_request(r, false);
    }
    r->peer_boot = p->boot; r->peer_sequence = p->sequence;
    r->peer_seen = true; r->last_peer_ms = now;
    r->peer_phase = (enum box_phase)p->payload[0];
    r->peer_relay = p->payload[1] != 0; r->peer_cycle = box_get32(p->payload + 4);
    r->faults &= ~BOX_FAULT_LINK; return true;
}
static void shutdown_request(box_rp *r, enum box_shutdown kind, uint32_t now) {
    if (r->shutdown != BOX_SHUTDOWN_NONE) {
        if (kind > r->shutdown) r->shutdown = kind;
        return;
    }
    r->shutdown = kind; r->shutdown_since = now; r->safe_received = false;
    r->shutdown_token = r->boot ^ (++r->shutdown_counter * 0x9e3779b9u);
    if (!r->shutdown_token) r->shutdown_token = 1;
    /* A shutdown request remains pending if a just-switched ToF relay needs
       its minimum dwell. tick() completes the OFF command before HOST cuts. */
    tof_set(r, false, now); radar_request(r, false);
    r->main_release_armed = false;
}
bool box_rp_command(box_rp *r, enum box_command command, uint32_t value, uint32_t now) {
    if (!r->main_hold) return false;
    switch (command) {
    case BOX_READY:
        if (!r->host_on) return false;
        r->host_ready = true; return true;
    case BOX_HOST_ON:
        if (r->shutdown != BOX_SHUTDOWN_NONE) return false;
        if (!r->host_on) {
            if (r->host_switched &&
                !elapsed(now, r->host_changed_ms, BOX_RELAY_MIN_DWELL_MS)) return false;
            r->host_ready = false; r->host_changed_ms = now; r->host_switched = true;
        }
        r->host_on = true; return true;
    case BOX_HOST_OFF: shutdown_request(r, BOX_SHUTDOWN_HOST, now); return true;
    case BOX_ALL_OFF: shutdown_request(r, BOX_SHUTDOWN_ALL, now); return true;
    case BOX_RADAR_SET:
        if (r->shutdown != BOX_SHUTDOWN_NONE) return false;
        if (r->desired_radar == (value != 0)) return true;
        radar_request(r, value != 0); return true;
    case BOX_TOF_SET:
        if (value && (!r->host_on || !r->host_ready || r->shutdown != BOX_SHUTDOWN_NONE))
            return false;
        if (value && !elapsed(now, r->host_changed_ms, BOX_HOST_ON_SETTLE_MS)) return false;
        return tof_set(r, value != 0, now);
    case BOX_SAFE_TO_CUT:
        if (r->shutdown == BOX_SHUTDOWN_NONE || !r->host_on || value != r->shutdown_token)
            return false;
        if (!r->safe_received) { r->safe_received = true; r->safe_since = now; }
        return true;
    case BOX_GET_STATUS: return true;
    default: return false;
    }
}
void box_rp_button_init(box_rp *r, bool down, uint32_t now) {
    r->button_initialized = true;
    r->button_raw_down = r->button_stable_down = down;
    r->startup_pending = true; r->startup_pressed = down;
    r->button_armed = r->button_long_sent = false;
    r->button_changed_ms = r->button_pressed_ms = r->startup_since = now;
}
void box_rp_button(box_rp *r, bool down, uint32_t now) {
    /* DPDT pole A closes the UPS switch loop. The isolated pole B grounds
       RP_BUTTON. Never join the two switch circuits or tie J51 to ground.
       Long ON is measured after MCU startup; short presses never start HOST. */
    if (!r->button_initialized) box_rp_button_init(r, down, now);
    if (down != r->button_raw_down) {
        r->button_raw_down = down; r->button_changed_ms = now;
    }
    bool released = false;
    if (r->button_stable_down != r->button_raw_down &&
        elapsed(now, r->button_changed_ms, 40u)) {
        r->button_stable_down = r->button_raw_down;
        if (r->button_stable_down) {
            r->button_pressed_ms = now; r->button_long_sent = false;
            r->startup_pressed = true;
        } else {
            released = true; r->button_armed = true;
        }
    }
    if (r->startup_pending) {
        if (r->button_stable_down && down &&
            elapsed(now, r->button_pressed_ms, 1000u)) {
            if (box_rp_command(r, BOX_HOST_ON, 0, now)) {
                r->startup_pending = false; r->button_armed = false;
            }
        } else if ((released && r->startup_pressed) ||
                   (!down && !r->button_stable_down &&
                    elapsed(now, r->startup_since, 3000u))) {
           /* Unexpected power-on or too short an ON press: finish
               the normal peripheral-off handshake, then release MAIN. */
            box_rp_command(r, BOX_ALL_OFF, 0, now);
            r->startup_pending = false; r->button_armed = false;
        }
        return;
    }
    if (!r->button_stable_down && !down) r->button_armed = true;
    if (r->button_armed && r->button_stable_down && down && !r->button_long_sent &&
        elapsed(now, r->button_pressed_ms, 2500u)) {
        box_rp_command(r, BOX_ALL_OFF, 0, now); r->button_long_sent = true;
    }
}
void box_rp_tick(box_rp *r, uint32_t now) {
    bool fresh = fresh_rp(r, now);
    if (r->peer_seen && !fresh && !(r->faults & BOX_FAULT_LINK)) {
        r->faults |= BOX_FAULT_LINK; radar_request(r, false);
        /* New link session rejects delayed pre-fault confirmations and permits
           sequence resynchronization after a long outage, without resetting RP
           or dropping MAIN/HOST. 'boot' is a protocol session nonce. */
        r->boot = r->boot * 1664525u + 1013904223u;
        if (!r->boot) r->boot = 1;
        r->peer_seen = false;
    }
    r->tx_enabled = fresh && r->desired_radar && r->peer_cycle == r->cycle &&
                    r->peer_phase == BOX_RUNNING && r->peer_relay;
    if (r->shutdown == BOX_SHUTDOWN_NONE) return;
    tof_set(r, false, now);
    if (elapsed(now, r->shutdown_since, 120000u)) r->faults |= BOX_FAULT_SHUTDOWN_TIMEOUT;
    bool radar_off = fresh && r->peer_cycle == r->cycle &&
                     r->peer_phase == BOX_OFF && !r->peer_relay && !r->tx_enabled;
    if (!radar_off || r->tof_on ||
        (r->tof_switched && !elapsed(now, r->tof_changed_ms, BOX_RADAR_OFF_SETTLE_MS))) {
        r->main_release_armed = false; return;
    }
    if (r->host_on) {
        if (!r->safe_received || !elapsed(now, r->safe_since, BOX_FINAL_CUT_DELAY_MS)) return;
        r->host_on = false; r->host_ready = false;
        r->host_switched = true; r->host_changed_ms = now;
    }
    if (r->shutdown == BOX_SHUTDOWN_ALL) {
        /* The J51 startup contact bypasses M16 while a person holds the
           button. A raw press blocks MAIN release; release is debounced.
           Start the complete MAIN delay again after the final release. */
        if (r->button_initialized && (r->button_raw_down || r->button_stable_down)) {
            r->main_release_armed = false; return;
        }
        if (!r->main_release_armed) {
            r->main_release_armed = true; r->main_release_since = now; return;
        }
        if (!elapsed(now, r->main_release_since, BOX_MAIN_RELEASE_DELAY_MS)) return;
        r->main_hold = false;
    }
    r->main_release_armed = false;
    r->shutdown = BOX_SHUTDOWN_NONE; r->shutdown_token = 0;
}
box_packet box_rp_request(const box_rp *r, uint16_t seq, bool released) {
    box_packet p = {.type = BOX_RP_LINK, .length = 8, .sequence = seq, .boot = r->boot};
    p.payload[0] = r->desired_radar; p.payload[1] = released;
    box_put32(p.payload + 4, r->cycle); return p;
}
box_packet box_rp_report(const box_rp *r, uint16_t seq, bool released) {
    box_packet p = {.type = BOX_HOST_STATUS, .length = 20, .sequence = seq, .boot = r->boot};
    p.payload[0] = r->host_on; p.payload[1] = r->main_hold; p.payload[2] = r->tof_on;
    p.payload[3] = (uint8_t)r->peer_phase; box_put32(p.payload + 4, r->faults);
    box_put32(p.payload + 8, r->shutdown_token); p.payload[12] = (uint8_t)r->shutdown;
    p.payload[13] = r->safe_received; p.payload[14] = released;
    box_put32(p.payload + 16, r->cycle); return p;
}
