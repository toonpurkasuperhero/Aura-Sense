# AuraSense Tier-1 sensor box (ESP32)

Built for this exact parts list: **MPU6050, DHT11, IR flame sensor, sound detection (microphone) module,
analog humidity module, I2C 1602 LCD**. It compiles cleanly with arduino-cli and the `esp32:esp32` core
(ESP32 Dev Module), using about 83% of flash and 22% of RAM.

## Wiring
| Module | Module pin | ESP32 pin | Notes |
|---|---|---|---|
| MPU6050 | VCC / GND / SDA / SCL | 3V3 / GND / **GPIO21** / **GPIO22** | Shares the I2C bus with the LCD (address 0x68) |
| I2C 1602 LCD | VCC / GND / SDA / SCL | **VIN (5 V)** / GND / **GPIO21** / **GPIO22** | Backpack address 0x27 or 0x3F, auto-detected. Turn the blue pot on the back if the text is invisible |
| DHT11 | VCC / DATA / GND | 3V3 / **GPIO4** / GND | Ambient temperature (1 °C resolution) and humidity |
| Flame sensor | VCC / GND / DO / AO | 3V3 / GND / **GPIO27** / **GPIO35** | Point it at the motor. Set the trip distance with the pot. AO is optional |
| Sound sensor | VCC / GND / AO / DO | 3V3 / GND / **GPIO34** / **GPIO26** | AO = loudness trend. DO trips on loud bangs (set with the pot) |
| Humidity module (analog) | VCC / GND / AO | 3V3 / GND / **GPIO32** | Optional (`HAS_ANALOG_HUMIDITY`). Raw value only; the DHT11 %RH is the calibrated one |

**Power the analog modules from 3V3, not 5 V.** Their outputs swing up to their supply voltage, and the ESP32 ADC pins
take at most 3.3 V. All analog inputs use ADC1 pins (32–39) because ADC2 does not work while Wi-Fi is on. The LCD
backpack runs from 5 V, and its I2C pull-ups work fine with the ESP32 in practice.

**Mounting:** fix the MPU6050 rigidly to the motor or bearing housing, with **Z along the shaft** and X/Y radial.
Foam tape kills the signal. Put the DHT11 and the microphone close to the machine, but not touching hot surfaces.

## Libraries (Arduino Library Manager)
- arduinoFFT (v2.x)
- ArduinoJson (v7.x)
- DHT sensor library (Adafruit), plus Adafruit Unified Sensor
- LiquidCrystal I2C (Frank de Brabander)

## Test on this Ubuntu laptop (same Wi-Fi as the ESP32)
1. **Use a 2.4 GHz network.** The ESP32 cannot see 5 GHz networks. Set your hotspot's band to 2.4 GHz and connect
   the laptop to the same hotspot.
2. **One-time permissions** (needs your password):
   - `sudo usermod -aG dialout $USER`, then log out and back in. This allows flashing over USB.
   - `sudo ufw allow 8000/tcp`. This lets the ESP32 reach the backend through the firewall.
3. `./scripts/run_all.sh` starts the backend, the UI and the simulator.
4. `./scripts/flash.sh doctor` checks the laptop IP, backend, firewall and USB port.
5. `./scripts/flash.sh check` flashes the **self-test**. The serial monitor and LCD show PASS/FAIL for each part:
   I2C, MPU6050, DHT11, flame (show a lighter), sound (clap), humidity, Wi-Fi and backend.
6. `./scripts/flash.sh node` flashes the real firmware. The **"Demo Rig (real ESP32)"** card appears in the
   dashboard at http://localhost:8000 next to the simulated machines.

`flash.sh` writes `config.h` (Wi-Fi, laptop IP, node id) for both sketches. That file is gitignored, so your Wi-Fi
password stays out of the code. Re-run `flash.sh` if the laptop's IP changes after reconnecting.

## Configure & flash (manual)
Edit the top of `aurasense_node/aurasense_node.ino`:
- `WIFI_SSID`, `WIFI_PASS`
- `BACKEND_URL` (the laptop's LAN IP, port 8000)
- `NODE_ID` (e.g. `motor_01`) and `RPM_HINT`
- `FLAME_ACTIVE_LOW` / `SOUND_ACTIVE_LOW`. Check your modules' DO LEDs: most flame modules pull DO **LOW** on flame.

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/aurasense_node
arduino-cli upload  --fqbn esp32:esp32:esp32 -p /dev/ttyUSB0 firmware/aurasense_node
```

## What the LCD shows
- **Line 1:** `OK z=0.4 ^`, i.e. the status, the vibration z-score, and `^` once the data reaches the backend (`x` if the post failed).
- **Line 2:** rotates every 2 s through vibration and dominant frequency, temperature and humidity, sound level, and then the alert reason or the IP address.
- On boot it shows `LEARNING 7/15` while it learns the baseline over about 30 s.
- On fire it shows `!! FLAME ALERT !! / Stop machine now`.

## Behaviour
- **WARN:** vibration z-score > 2, temperature +6 °C, or humidity > 85 %RH.
- **ALERT:** z > 3 for 3 windows, temperature +10 °C, or RMS > 0.3 g absolute.
- **FLAME:** an immediate ALERT, rated CRITICAL by the backend and the Safety Auditor.
- The flame and sound digital outputs are checked 32 times during every 1-second vibration window, so a short flicker or bang is still caught.
- Telemetry is posted as JSON every 2 s to `/api/telemetry`. Failed posts are buffered (30) and replayed.
- The box polls `/api/nodes/<id>/command`. The dashboard's **Re-learn baseline** button resets the baseline (use it after a repair).
- If the venue Wi-Fi blocks devices, put the laptop and the ESP32 on a **phone hotspot**.

## Demo rig
A table fan or small motor:
- tape a coin to a blade for imbalance;
- loosen a mounting screw for looseness;
- show a lighter flame to the flame sensor for a fire alert;
- breathe on the DHT11 for a humidity rise.
