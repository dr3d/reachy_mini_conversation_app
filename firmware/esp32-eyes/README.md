# ESP32 Eyes Firmware

Experimental ESP32-S3 firmware for Reachy Mini face displays. It drives two 240x240 GC9A01 round eye screens plus an optional third mouth screen, with gaze, blinks, moods, idle beats, mouth shapes, brightness, display flip, USB serial commands, and an HTTP API.

## Build And Flash

Use PlatformIO from this folder:

```bash
pio run
pio run -t upload
pio device monitor
```

The default target is `esp32-s3-devkitc-1` from `platformio.ini`.

## Wiring And Private Config

Display pins and timing defaults live in `include/reachy_config.h`. The default three-display wiring shares GPIO4/5/6/7 for SCLK/MOSI/DC/RST, with GPIO15/16/17 as left-eye/right-eye/mouth CS.

For local Wi-Fi credentials, copy:

```bash
cp include/reachy_config_private.example.h include/reachy_config_private.h
```

Then fill in `REACHY_WIFI_SSID` and `REACHY_WIFI_PASSWORD`. The private header is ignored by git.

By default, the board keeps a setup access point available named `ReachyEyes-S3` with password `reachyeyes`. The AP URL is usually:

```text
http://192.168.4.1/
```

From that AP page, use the Wi-Fi card to enter your LAN SSID and password. The password field is plain text for easy bench setup. The board saves those credentials in ESP32 non-volatile storage and reboots; saved passwords are not returned by the status API. Use **Clear Saved** to remove stored credentials and reboot back to the compile-time/default behavior. Set `REACHY_AP_ALWAYS_ON` to `0` in `include/reachy_config.h` if you want the AP to appear only as a fallback.

When station Wi-Fi succeeds, the serial monitor prints both the setup AP and LAN address:

```text
WiFi AP SSID: ReachyEyes-S3
Face UI AP URL: http://192.168.4.1/
WiFi IP: 192.168.x.x
Face UI URL: http://192.168.x.x/
mDNS URL: http://reachyeyes-s3.local/
```

Use the printed IP if `.local` name resolution is unavailable on your computer or network.

## Browser Test Panel

Open the board root URL to control the face directly:

```text
http://reachyeyes-s3.local/
```

or, on the default access point:

```text
http://192.168.4.1/
```

The built-in panel controls eye style, mood/expression, idle beats, mouth style/shape/talking energy, gaze, blink/wink, sleep, release, brightness, and display flip.

## OTA Firmware Updates

After one USB flash of an OTA-capable build, future firmware updates can be uploaded from the browser test panel. Build the firmware:

```bash
pio run
```

Then open the board URL, use the **OTA Firmware** card, and upload:

```text
.pio/build/esp32-s3-devkitc-1/firmware.bin
```

The board reboots after a successful upload. Keep USB flashing available as a fallback, and do not upload `bootloader.bin` or `partitions.bin` through this panel.

## HTTP API

Useful read endpoints:

```bash
curl "$EYES_URL/state"
curl "$EYES_URL/styles"
curl "$EYES_URL/emotions"
curl "$EYES_URL/moods"
curl "$EYES_URL/mouth_shapes"
curl "$EYES_URL/mouth_styles"
curl "$EYES_URL/beats"
```

Common commands:

```bash
curl -X POST "$EYES_URL/style" -H "Content-Type: application/json" -d '{"name":"robot"}'
curl -X POST "$EYES_URL/expression" -H "Content-Type: application/json" -d '{"name":"suspicious","duration":4}'
curl -X POST "$EYES_URL/mouth" -H "Content-Type: application/json" -d '{"style":"human","shape":"open","talking":true,"energy":0.7,"duration":0}'
curl -X POST "$EYES_URL/gaze" -H "Content-Type: application/json" -d '{"x":1,"y":0,"duration":0,"move_ms":180}'
curl -X POST "$EYES_URL/release" -H "Content-Type: application/json" -d '{}'
```

Set `EYES_URL` to the board URL first, for example:

```bash
EYES_URL=http://reachyeyes-s3.local
```

## Conversation App Integration

In the conversation app `.env`, point the app at the board:

```env
REACHY_MINI_EYES_BASE_URL=http://reachyeyes-s3.local/
```

The app then sends high-level cues through the `set_eyes` tool and automatic conversation/motion choreography. The firmware owns rendering and animation timing.
