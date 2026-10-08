#include "../common/power.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct { box_rp r; box_s3 s; uint32_t now; uint16_t rs, ss; } rig;
static void step(rig *x, unsigned ms) {
    x->now += ms;
    box_packet p = box_rp_request(&x->r, ++x->rs, !x->r.tx_enabled);
    assert(box_s3_receive(&x->s, &p, x->now));
    box_s3_tick(&x->s, x->now, !x->s.tx_enabled);
    p = box_s3_report(&x->s, ++x->ss, !x->s.tx_enabled);
    assert(box_rp_receive(&x->r, &p, x->now));
    box_rp_tick(&x->r, x->now);
}
static rig start(void) {
    rig x = {0}; box_rp_init(&x.r, 100); box_s3_init(&x.s, 200);
    step(&x, 1); step(&x, 50);
    assert(x.s.phase == BOX_OFF && !x.r.tx_enabled && x.r.main_hold);
    return x;
}
static void run_radar(rig *x) {
    assert(box_rp_command(&x->r, BOX_RADAR_SET, 1, x->now));
    if (x->s.relay_switched && !x->s.relay_on &&
        (uint32_t)(x->now - x->s.relay_changed_ms) < BOX_RELAY_MIN_DWELL_MS)
        step(x, BOX_RELAY_MIN_DWELL_MS - (uint32_t)(x->now - x->s.relay_changed_ms));
    else
        step(x, 1);
    assert(x->s.relay_on && !x->s.tx_enabled && !x->r.tx_enabled);
    step(x, 299); assert(!x->s.tx_enabled && !x->r.tx_enabled);
    step(x, 1); assert(x->s.tx_enabled && x->r.tx_enabled);
}
static void test_protocol(void) {
    const uint8_t known[] = "123456789";
    assert(box_crc16(known, 9) == 0x29b1);
    box_packet p = {.type = BOX_HOST_COMMAND, .length = 5, .sequence = 65535,
                    .boot = 0x12345678};
    p.payload[0] = BOX_ALL_OFF; box_put32(p.payload + 1, 0xfedcba98);
    uint8_t b[64]; box_encode(&p, b); box_packet got;
    assert(box_decode(b, &got));
    assert(got.sequence == p.sequence && got.boot == p.boot &&
           !memcmp(got.payload, p.payload, 5));
    for (unsigned bit = 0; bit < 512; ++bit) {
        b[bit / 8] ^= 1u << (bit % 8);
        assert(!box_decode(b, &got));
        b[bit / 8] ^= 1u << (bit % 8);
    }
    box_stream stream = {0}; unsigned accepted = 0;
    for (unsigned i = 0; i < 17; ++i) box_stream_byte(&stream, b[i], &got);
    for (unsigned i = 0; i < 64; ++i) accepted += box_stream_byte(&stream, b[i], &got);
    assert(accepted == 1 && got.boot == p.boot);
    assert(!box_sequence_newer(42, 42) && !box_sequence_newer(41, 42));
    assert(box_sequence_newer(0, 65535) && !box_sequence_newer(65535, 0));
    box_radar_parser radar = {0}; uint8_t raw[30] = {0xaa, 0xff, 3, 0}, out[30];
    raw[28] = 0x55; raw[29] = 0xcc;
    accepted = 0;
    for (unsigned i = 0; i < 13; ++i) box_radar_byte(&radar, raw[i], out);
    for (unsigned i = 0; i < 30; ++i) accepted += box_radar_byte(&radar, raw[i], out);
    assert(accepted == 1 && !memcmp(raw, out, 30));
}
static void test_release_handshake(void) {
    rig x = start();
    assert(box_rp_command(&x.r, BOX_RADAR_SET, 1, x.now));
    box_packet p = box_rp_request(&x.r, ++x.rs, false);
    assert(box_s3_receive(&x.s, &p, ++x.now));
    box_s3_tick(&x.s, x.now, true);
    assert(!x.s.relay_on && !x.s.tx_enabled);
    p = box_rp_request(&x.r, ++x.rs, true);
    assert(box_s3_receive(&x.s, &p, ++x.now));
    box_s3_tick(&x.s, x.now, false);
    assert(!x.s.relay_on);
    box_s3_tick(&x.s, x.now, true);
    assert(x.s.relay_on && !x.s.tx_enabled);
    step(&x, 300); assert(x.r.tx_enabled && x.s.tx_enabled);
    assert(box_rp_command(&x.r, BOX_RADAR_SET, 0, x.now));
    p = box_rp_request(&x.r, ++x.rs, false);
    assert(box_s3_receive(&x.s, &p, ++x.now));
    box_s3_tick(&x.s, x.now, true);
    assert(x.s.relay_on && !x.s.tx_enabled); /* RP has not released its pin. */
    p = box_rp_request(&x.r, ++x.rs, true);
    assert(box_s3_receive(&x.s, &p, ++x.now));
    box_s3_tick(&x.s, x.now, false);
    assert(x.s.relay_on); /* Local GPIO adapter has not finished releasing. */
    box_s3_tick(&x.s, x.now, true);
    assert(!x.s.relay_on && x.s.phase == BOX_STOPPING);
    step(&x, 50); assert(x.s.phase == BOX_OFF && !x.r.tx_enabled);
}
static void test_link_failure(void) {
    rig x = start(); run_radar(&x);
    assert(box_rp_command(&x.r, BOX_HOST_ON, 0, x.now));
    box_packet old_rp = box_rp_request(&x.r, ++x.rs, true);
    box_packet old_s3 = box_s3_report(&x.s, ++x.ss, true);
    uint32_t nonce = x.r.boot;
    x.now += 500;
    box_s3_tick(&x.s, x.now, false);
    box_rp_tick(&x.r, x.now);
    assert(x.s.relay_on && !x.s.tx_enabled && !x.r.tx_enabled);
    assert(x.r.host_on && x.r.main_hold && x.r.boot != nonce);
    assert(!box_rp_receive(&x.r, &old_s3, x.now));
    /* Previously accepted sequence cannot extend the S3 liveness deadline. */
    old_rp.sequence = x.s.peer_sequence;
    assert(!box_s3_receive(&x.s, &old_rp, x.now));
    step(&x, 1); step(&x, 50);
    assert(!x.s.relay_on && x.s.phase == BOX_OFF && !x.r.desired_radar);
    assert(x.r.host_on && x.r.main_hold);
    run_radar(&x);
    box_s3_init(&x.s, 201); /* S3 reboot must cancel the old RP enable cycle. */
    step(&x, 1);
    assert(!x.r.desired_radar && !x.r.tx_enabled);
    step(&x, BOX_RELAY_MIN_DWELL_MS); step(&x, 50);
    assert(!x.s.relay_on && x.s.phase == BOX_OFF);
}
static void test_shutdown(void) {
    rig x = start(); run_radar(&x);
    assert(!box_rp_command(&x.r, BOX_TOF_SET, 1, x.now));
    assert(box_rp_command(&x.r, BOX_HOST_ON, 0, x.now));
    assert(!box_rp_command(&x.r, BOX_TOF_SET, 1, x.now));
    assert(box_rp_command(&x.r, BOX_READY, 0, x.now));
    assert(!box_rp_command(&x.r, BOX_TOF_SET, 1, x.now));
    step(&x, 499);
    assert(!box_rp_command(&x.r, BOX_TOF_SET, 1, x.now));
    step(&x, 1);
    assert(box_rp_command(&x.r, BOX_TOF_SET, 1, x.now));
    assert(box_rp_command(&x.r, BOX_HOST_OFF, 0, x.now));
    uint32_t token = x.r.shutdown_token;
    assert(token && x.r.tof_on);
    step(&x, 249); assert(x.r.tof_on && x.r.host_on);
    step(&x, 1); assert(!x.r.tof_on && x.r.host_on);
    assert(!box_rp_command(&x.r, BOX_SAFE_TO_CUT, token ^ 1, x.now));
    assert(!box_rp_command(&x.r, BOX_HOST_ON, 0, x.now));
    assert(!box_rp_command(&x.r, BOX_RADAR_SET, 1, x.now));
    for (unsigned i = 0; i < 1210; ++i) step(&x, 100);
    assert(x.r.host_on && x.r.main_hold &&
           (x.r.faults & BOX_FAULT_SHUTDOWN_TIMEOUT));
    assert(box_rp_command(&x.r, BOX_SAFE_TO_CUT, token, x.now));
    for (unsigned i = 0; i < 9; ++i) step(&x, 100);
    assert(x.r.host_on);
    step(&x, 100); assert(!x.r.host_on && x.r.main_hold);
    assert(!box_rp_command(&x.r, BOX_HOST_ON, 0, x.now));
    step(&x, 249); assert(!box_rp_command(&x.r, BOX_HOST_ON, 0, x.now));
    step(&x, 1);
    assert(box_rp_command(&x.r, BOX_HOST_ON, 0, x.now));
    assert(box_rp_command(&x.r, BOX_ALL_OFF, 0, x.now));
    assert(x.r.shutdown_token != token);
    assert(!box_rp_command(&x.r, BOX_SAFE_TO_CUT, token, x.now));
    assert(box_rp_command(&x.r, BOX_SAFE_TO_CUT, x.r.shutdown_token, x.now));
    /* A valid host ACK alone cannot bypass a missing radar-off confirmation. */
    x.now += 1001; box_rp_tick(&x.r, x.now);
    assert(x.r.host_on && x.r.main_hold);
    step(&x, 1); step(&x, 50);
    assert(!x.r.host_on && x.r.main_hold);
    step(&x, 249); assert(x.r.main_hold);
    step(&x, 1); assert(!x.r.main_hold);
    assert(!box_rp_command(&x.r, BOX_HOST_ON, 0, x.now));
}
static void test_relay_dwell(void) {
    rig x = start(); run_radar(&x);
    uint32_t cycle = x.r.cycle;
    assert(box_rp_command(&x.r, BOX_RADAR_SET, 1, x.now));
    assert(x.r.cycle == cycle && x.r.tx_enabled);
    assert(box_rp_command(&x.r, BOX_RADAR_SET, 0, x.now));
    step(&x, 1); assert(!x.s.relay_on);
    assert(box_rp_command(&x.r, BOX_RADAR_SET, 1, x.now));
    step(&x, 249);
    assert(!x.s.relay_on && !x.s.tx_enabled && !x.r.tx_enabled);
    step(&x, 1); assert(x.s.relay_on && !x.s.tx_enabled && !x.r.tx_enabled);
    step(&x, 299); assert(!x.s.tx_enabled && !x.r.tx_enabled);
    step(&x, 1); assert(x.s.tx_enabled && x.r.tx_enabled);

    /* Exercise a ToF dwell interval across the 32-bit millisecond wrap. */
    x.now = UINT32_MAX - 1000;
    assert(box_rp_command(&x.r, BOX_HOST_ON, 0, x.now));
    assert(box_rp_command(&x.r, BOX_READY, 0, x.now));
    step(&x, 900);
    assert(box_rp_command(&x.r, BOX_TOF_SET, 1, x.now));
    assert(box_rp_command(&x.r, BOX_TOF_SET, 1, x.now)); /* Idempotent. */
    assert(!box_rp_command(&x.r, BOX_TOF_SET, 0, x.now));
    step(&x, 249); assert(!box_rp_command(&x.r, BOX_TOF_SET, 0, x.now));
    step(&x, 1); assert(box_rp_command(&x.r, BOX_TOF_SET, 0, x.now));
    assert(!box_rp_command(&x.r, BOX_TOF_SET, 1, x.now));
    step(&x, 250); assert(box_rp_command(&x.r, BOX_TOF_SET, 1, x.now));
}
static void test_main_delay_link_loss(void) {
    rig x = start();
    assert(box_rp_command(&x.r, BOX_HOST_ON, 0, x.now));
    assert(box_rp_command(&x.r, BOX_ALL_OFF, 0, x.now));
    assert(box_rp_command(&x.r, BOX_SAFE_TO_CUT, x.r.shutdown_token, x.now));
    for (unsigned i = 0; i < 10; ++i) step(&x, 100);
    assert(!x.r.host_on && x.r.main_hold && x.r.main_release_armed);
    x.now += BOX_LINK_TIMEOUT_MS; box_rp_tick(&x.r, x.now);
    assert(x.r.main_hold && !x.r.main_release_armed);
    step(&x, 1); step(&x, 50);
    assert(x.r.main_hold && x.r.main_release_armed);
    step(&x, 249); assert(x.r.main_hold);
    step(&x, 1); assert(!x.r.main_hold);
}
static void test_wrap_and_stale_cycle(void) {
    rig x = start(); x.now = UINT32_MAX - 100;
    step(&x, 1); /* Receive fresh traffic near clock wrap. */
    run_radar(&x);
    assert(x.now < 1000 && x.r.tx_enabled);
    box_packet p = box_s3_report(&x.s, ++x.ss, false);
    assert(box_rp_command(&x.r, BOX_RADAR_SET, 0, x.now));
    assert(box_rp_command(&x.r, BOX_RADAR_SET, 1, x.now));
    assert(box_rp_receive(&x.r, &p, x.now));
    box_rp_tick(&x.r, x.now); assert(!x.r.tx_enabled);
    p.sequence--; assert(!box_rp_receive(&x.r, &p, x.now));
    step(&x, 1); step(&x, 1); step(&x, 300);
    assert(x.r.tx_enabled && x.s.tx_enabled);
}
static void button_step(rig *x, bool down, uint32_t dt) {
    x->now += dt;
    box_rp_button(&x->r, down, x->now);
    step(x, 0);
}
static void test_rear_longpress(void) {
    rig x = start();
    box_rp_button_init(&x.r, true, x.now);
    button_step(&x, true, 999); assert(!x.r.host_on);
    button_step(&x, true, 1); assert(x.r.host_on);
    /* Holding the startup press must never become a shutdown press. */
    for (unsigned i = 0; i < 60; ++i) button_step(&x, true, 100);
    assert(x.r.shutdown == BOX_SHUTDOWN_NONE);
    button_step(&x, false, 1); button_step(&x, false, 40);
    /* A short or bouncing press has no HOST toggle action. */
    button_step(&x, true, 1); button_step(&x, false, 20);
    button_step(&x, false, 40);
    assert(x.r.host_on && x.r.shutdown == BOX_SHUTDOWN_NONE);
    button_step(&x, true, 1); button_step(&x, true, 40);
    for (unsigned i = 0; i < 24; ++i) button_step(&x, true, 100);
    assert(x.r.shutdown == BOX_SHUTDOWN_NONE);
    button_step(&x, true, 100);
    assert(x.r.shutdown == BOX_SHUTDOWN_ALL && x.r.host_on);
    uint32_t token = x.r.shutdown_token;
    assert(box_rp_command(&x.r, BOX_SAFE_TO_CUT, token, x.now));
    for (unsigned i = 0; i < 20; ++i) button_step(&x, true, 100);
    assert(!x.r.host_on && x.r.main_hold && !x.r.main_release_armed);
    /* Release bounce must not cause a power pulse against the ON contact. */
    button_step(&x, false, 1); button_step(&x, false, 20);
    button_step(&x, true, 1); button_step(&x, true, 40);
    assert(x.r.main_hold && !x.r.main_release_armed);
    button_step(&x, false, 1); button_step(&x, false, 40);
    assert(x.r.main_release_armed);
    button_step(&x, false, 249); assert(x.r.main_hold);
    button_step(&x, false, 1); assert(!x.r.main_hold);
}
static void test_short_start_and_unrequested_power(void) {
    rig x = start();
    x.now = UINT32_MAX - 80;
    box_rp_button_init(&x.r, true, x.now);
    button_step(&x, false, 100); button_step(&x, false, 40);
    assert(!x.r.host_on && x.r.shutdown == BOX_SHUTDOWN_ALL);
    for (unsigned i = 0; i < 10; ++i) button_step(&x, false, 100);
    assert(!x.r.main_hold);
    x = start();
    box_rp_button_init(&x.r, false, x.now);
    for (unsigned i = 0; i < 29; ++i) button_step(&x, false, 100);
    assert(!x.r.host_on && x.r.shutdown == BOX_SHUTDOWN_NONE);
    button_step(&x, false, 100);
    assert(x.r.shutdown == BOX_SHUTDOWN_ALL);
}
int main(void) {
    test_protocol(); test_release_handshake(); test_link_failure();
    test_shutdown(); test_wrap_and_stale_cycle(); test_relay_dwell();
    test_main_delay_link_loss();
    test_rear_longpress(); test_short_start_and_unrequested_power();
    puts("PASS: protocol corruption/recovery, release handshake, link/reboot faults, "
         "shutdown authorization/timeouts, clock wrap/stale cycles, relay dwell, "
         "HOST/ToF sequencing, delayed MAIN release with link-loss interlock, "
         "long ON/OFF, release interlock, startup bounce and accidental power-on");
}
