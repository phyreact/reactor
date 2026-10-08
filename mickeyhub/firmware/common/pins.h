#pragma once
/* Actual chip GPIO numbers, never Arduino D-number aliases. */
#define RP_MAIN_HOLD 28 /* Original LOW-active M16 holds the UPS switch loop. */
#define RP_HOST_RELAY 27
#define RP_TOF_RELAY 2
#define RP_BUTTON 26 /* Rear DPDT sensing pole; replaces the removed front key. */
#define RP_RADAR_TX 4
#define RP_RADAR_RX 5
#define RP_ZERO_TX 0
#define RP_ZERO_RX 1
#define RP_I2C_SDA 6
#define RP_I2C_SCL 7
#define S3_RADAR_RELAY 2
#define S3_I2C_SDA 5
#define S3_I2C_SCL 6
#define BOX_RADAR_BAUD 256000
#define BOX_ZERO_BAUD 115200
#define S3_RADAR_TX_VALUES {3, 7, 1}
#define S3_RADAR_RX_VALUES {4, 8, 9}
