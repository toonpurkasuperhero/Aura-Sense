/*
 * AuraSense Tier-1 Sentinel node (ESP32)
 * -------------------------------------
 * Sensors in this build:
 *   - MPU6050          tri-axial vibration (I2C)
 *   - DHT11            ambient temperature + relative humidity
 *   - Humidity module  optional analog humidity sensor (HR202 / HR31 type, AO pin)
 *   - Flame sensor     IR flame module (DO + optional AO)
 *   - Sound sensor     microphone module (KY-037 / KY-038 type, AO + DO)
 *   - I2C 1602 LCD     local status display (PCF8574 backpack, shares the I2C bus)
 *
 * Every ~2 s it samples 1024 accelerometer readings at ~1 kHz, computes per-axis
 * RMS, peak, crest factor, kurtosis and the top-5 FFT peaks, learns a baseline for
 * the first LEARN_WINDOWS windows, then raises WARN / ALERT on vibration z-score,
 * an absolute vibration limit, temperature rise, high humidity or FLAME (immediate).
 * Telemetry is POSTed as JSON to the AuraSense backend; failed posts are buffered.
 *
 * Libraries (Arduino Library Manager):
 *   - arduinoFFT (v2.x, Enrique Condes)       - ArduinoJson (v7.x, Benoit Blanchon)
 *   - DHT sensor library (Adafruit) + Adafruit Unified Sensor
 *   - LiquidCrystal I2C (Frank de Brabander)
 * Board: "ESP32 Dev Module" (esp32 core >= 2.0)
 */
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <DHT.h>
#include <LiquidCrystal_I2C.h>
#include <ArduinoJson.h>
#include <arduinoFFT.h>
#include <time.h>

// ------------------------------------------------------------------ user config
// Wi-Fi, backend address and node id live in config.h (written by scripts/flash.sh, not committed).
#if __has_include("config.h")
#include "config.h"
#endif
#ifndef CFG_WIFI_SSID
#define CFG_WIFI_SSID   "YOUR_WIFI_SSID"
#define CFG_WIFI_PASS   "YOUR_WIFI_PASSWORD"
#define CFG_BACKEND_URL "http://192.168.1.100:8000"
#define CFG_NODE_ID     "esp32_rig"
#define CFG_RPM_HINT    1440.0
#endif
const char* WIFI_SSID   = CFG_WIFI_SSID;
const char* WIFI_PASS   = CFG_WIFI_PASS;
const char* BACKEND_URL = CFG_BACKEND_URL;   // laptop running the backend
const char* NODE_ID     = CFG_NODE_ID;       // must match a machine profile (esp32_rig = real hardware rig)
const float RPM_HINT    = CFG_RPM_HINT;      // nameplate rpm of the machine

const bool HAS_ANALOG_HUMIDITY = true;   // moisture / analog humidity module on PIN_HUM_AO
const bool HAS_SOUND           = true;   // sound module wired: AO PIN_SOUND_AO, DO PIN_SOUND_DO
const int  MOIST_DRY = 4095, MOIST_WET = 1200;  // ADC reading in dry air / in water: calibrate for your probe
const bool FLAME_ACTIVE_LOW    = true;   // most LM393 flame modules pull DO LOW when they see flame
const bool SOUND_ACTIVE_LOW    = false;  // KY-037/038 DO usually goes HIGH on a loud sound
const bool HAS_BUZZER          = false;  // optional active buzzer on PIN_BUZZER

// ------------------------------------------------------------------ pins
// I2C bus shared by MPU6050 (0x68) and the LCD backpack (0x27 or 0x3F)
const int PIN_SDA = 21, PIN_SCL = 22;
const int PIN_DHT = 4;          // DHT11 data (module has its own pull-up)
const int PIN_SOUND_AO = 32;    // sound module AO (ADC1 CH4)
const int PIN_FLAME_AO = 35;    // flame module AO   (ADC1, input only, optional)
const int PIN_HUM_AO = 34;      // moisture / humidity module AO (ADC1, input only)
const int PIN_FLAME_DO = 23;    // flame module DO
const int PIN_SOUND_DO = 18;    // sound module DO (threshold set by potentiometer)
const int PIN_BUZZER = 33;      // optional

// ------------------------------------------------------------------ signal config
const uint16_t N = 1024;          // samples per window
const float FS = 1000.0;          // target sample rate (Hz)
const int LEARN_WINDOWS = 15;     // ~30 s baseline learning
const float Z_ALERT = 3.0, Z_WARN = 2.0;
const float DT_ALERT = 10.0, DT_WARN = 6.0;   // °C over baseline (DHT11 = ambient, 1 °C resolution)
const float HUM_WARN = 85.0;                  // %RH: condensation / insulation / corrosion risk
const float ABS_ALERT_G = 0.3;                // combined RMS, always alerts
const uint32_t POST_INTERVAL_MS = 2000;
const uint32_t CMD_POLL_MS = 10000;

const uint8_t MPU_ADDR = 0x68;
float ax[N], ay[N], az[N];
float vReal[N], vImag[N];
ArduinoFFT<float> FFT(vReal, vImag, N, FS);
DHT dht(PIN_DHT, DHT22);
LiquidCrystal_I2C* lcd = nullptr;

// baseline (Welford running stats)
int learnCount = 0;
double bMean = 0, bM2 = 0, bTemp = 0, bSound = 0;
bool baselineReady = false;
int overCount = 0;
float tempC = NAN, humPct = NAN, moistPct = NAN;
bool hasMpu = false;
int lcdPage = 0;

// offline buffer
const int BUF_MAX = 30;
String buffer[BUF_MAX];
int bufHead = 0, bufCount = 0;
uint32_t lastCmdPoll = 0;

// ------------------------------------------------------------------ MPU6050 (raw registers, fast)
void mpuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU_ADDR); Wire.write(reg); Wire.write(val); Wire.endTransmission();
}
void mpuInit() {
  mpuWrite(0x6B, 0x00);   // wake up
  mpuWrite(0x1A, 0x01);   // DLPF 184 Hz
  mpuWrite(0x19, 0x00);   // sample rate = 1 kHz
  mpuWrite(0x1C, 0x08);   // accel ±4 g (8192 LSB/g)
}
inline void mpuRead(float &x, float &y, float &z) {
  Wire.beginTransmission(MPU_ADDR); Wire.write(0x3B); Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, (uint8_t)6);
  int16_t rx = (Wire.read() << 8) | Wire.read();
  int16_t ry = (Wire.read() << 8) | Wire.read();
  int16_t rz = (Wire.read() << 8) | Wire.read();
  x = rx / 8192.0f; y = ry / 8192.0f; z = rz / 8192.0f;
}

// ------------------------------------------------------------------ LCD (auto-detect 0x27 / 0x3F)
bool i2cPresent(uint8_t addr) { Wire.beginTransmission(addr); return Wire.endTransmission() == 0; }

void lcdInit() {
  uint8_t addr = i2cPresent(0x27) ? 0x27 : i2cPresent(0x3F) ? 0x3F : 0;
  if (!addr) { Serial.println("LCD not found on 0x27/0x3F"); return; }
  lcd = new LiquidCrystal_I2C(addr, 16, 2);
  lcd->init(); lcd->backlight();
}

void lcdLine(uint8_t row, String s) {
  if (!lcd) return;
  while (s.length() < 16) s += ' ';
  lcd->setCursor(0, row); lcd->print(s.substring(0, 16));
}

// ------------------------------------------------------------------ helpers
bool flameNow() { return digitalRead(PIN_FLAME_DO) == (FLAME_ACTIVE_LOW ? LOW : HIGH); }
bool soundTrigNow() { return HAS_SOUND && digitalRead(PIN_SOUND_DO) == (SOUND_ACTIVE_LOW ? LOW : HIGH); }

float meanRemove(float* v) {
  double m = 0; for (int i = 0; i < N; i++) m += v[i]; m /= N;
  double s = 0; for (int i = 0; i < N; i++) { v[i] -= m; s += v[i] * v[i]; }
  return sqrt(s / N);  // RMS of AC part
}

float soundLevel() {     // microphone AO peak-to-peak over ~20 ms, averaged (ADC units)
  if (!HAS_SOUND) return NAN;
  uint32_t acc = 0;
  for (int k = 0; k < 5; k++) {
    int mn = 4095, mx = 0; uint32_t t0 = millis();
    while (millis() - t0 < 20) { int s = analogRead(PIN_SOUND_AO); mn = min(mn, s); mx = max(mx, s); }
    acc += (mx - mn);
  }
  return acc / 5.0;
}

float analogAvg(int pin) { uint32_t s = 0; for (int i = 0; i < 16; i++) s += analogRead(pin); return s / 16.0; }

String isoNow() {
  struct tm t;
  if (!getLocalTime(&t, 10)) return "";
  char b[32]; strftime(b, sizeof(b), "%Y-%m-%dT%H:%M:%SZ", &t); return String(b);
}

bool postJson(const String& body) {
  if (WiFi.status() != WL_CONNECTED) return false;
  HTTPClient http;
  http.begin(String(BACKEND_URL) + "/api/telemetry");
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(4000);
  int code = http.POST(body);
  http.end();
  return code >= 200 && code < 300;
}

void bufferPush(const String& s) {
  buffer[(bufHead + bufCount) % BUF_MAX] = s;
  if (bufCount < BUF_MAX) bufCount++; else bufHead = (bufHead + 1) % BUF_MAX;
}

void flushBuffer() {
  while (bufCount > 0 && WiFi.status() == WL_CONNECTED) {
    String s = buffer[bufHead];
    s.replace("\"buffered\":false", "\"buffered\":true");
    if (!postJson(s)) break;
    bufHead = (bufHead + 1) % BUF_MAX; bufCount--;
  }
}

void pollCommand() {
  if (millis() - lastCmdPoll < CMD_POLL_MS || WiFi.status() != WL_CONNECTED) return;
  lastCmdPoll = millis();
  HTTPClient http;
  http.begin(String(BACKEND_URL) + "/api/nodes/" + NODE_ID + "/command");
  if (http.GET() == 200) {
    JsonDocument cmd;
    if (!deserializeJson(cmd, http.getString()) && (cmd["relearn"] | false)) {
      learnCount = 0; bMean = bM2 = bTemp = bSound = 0; baselineReady = false; overCount = 0;
      Serial.println("relearning baseline");
    }
  }
  http.end();
}

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  lcdLine(0, "AuraSense"); lcdLine(1, "WiFi connecting");
  WiFi.mode(WIFI_STA); WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 8000) { delay(250); Serial.print("."); }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\nWiFi OK %s\n", WiFi.localIP().toString().c_str());
    lcdLine(1, WiFi.localIP().toString());
    configTime(0, 0, "pool.ntp.org", "time.google.com");
  } else {
    lcdLine(1, "WiFi failed-retry");
  }
}

void showLcd(const char* status, float comb, float z, float dom, float snd, bool flame, bool posted, const String& reason) {
  if (!lcd) return;
  Wire.setClock(100000);   // PCF8574 backpack is happiest at 100 kHz
  if (flame) {
    lcdLine(0, "!! FLAME ALERT !!");
    lcdLine(1, "Stop machine now");
  } else {
    char l0[17];
    if (!baselineReady) snprintf(l0, sizeof(l0), "LEARNING %2d/%-2d", learnCount, LEARN_WINDOWS);
    else snprintf(l0, sizeof(l0), "%-5s z=%-5.1f%s", status, isnan(z) ? 0.0 : z, posted ? "^" : "x");
    lcdLine(0, l0);
    char l1[33];
    switch (lcdPage++ % 4) {
      case 0: snprintf(l1, sizeof(l1), "Vib %.3fg %3.0fHz", comb, dom); break;
      case 1: snprintf(l1, sizeof(l1), "T %.0fC  H %.0f%%", tempC, humPct); break;
      case 2: if (HAS_SOUND) snprintf(l1, sizeof(l1), "Sound %4.0f", snd); else snprintf(l1, sizeof(l1), "Moist %3.0f%%", moistPct); break;
      default:
        if (reason.length()) { lcdLine(1, reason); Wire.setClock(400000); return; }
        snprintf(l1, sizeof(l1), "%s", WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "WiFi offline");
    }
    lcdLine(1, l1);
  }
  Wire.setClock(400000);
}

// ------------------------------------------------------------------ setup / loop
void setup() {
  Serial.begin(115200);
  pinMode(PIN_FLAME_DO, INPUT);
  if (HAS_SOUND) pinMode(PIN_SOUND_DO, INPUT);
  if (HAS_BUZZER) pinMode(PIN_BUZZER, OUTPUT);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);   // 0-3.3 V range on the analog pins
  Wire.begin(PIN_SDA, PIN_SCL, 100000);
  lcdInit();
  lcdLine(0, "AuraSense node"); lcdLine(1, NODE_ID);
  Wire.setClock(400000);
  hasMpu = i2cPresent(MPU_ADDR);
  Serial.printf("MPU6050 %s, LCD %s\n", hasMpu ? "found" : "NOT found", lcd ? "found" : "NOT found");
  if (hasMpu) mpuInit();
  dht.begin();
  connectWifi();
}

void loop() {
  uint32_t loopStart = millis();
  connectWifi();
  pollCommand();

  // 1) sample accelerometer at ~1 kHz; check the flame + sound digital outputs during the window
  uint32_t period = (uint32_t)(1e6 / FS), t = micros();
  int flameHits = 0, soundHits = 0;
  for (int i = 0; i < N; i++) {
    while ((uint32_t)(micros() - t) < period) {}
    t += period;
    if (hasMpu) mpuRead(ax[i], ay[i], az[i]); else ax[i] = ay[i] = az[i] = 0;
    if ((i & 31) == 0) { flameHits += flameNow(); soundHits += soundTrigNow(); }
  }
  bool soundEvent = soundHits >= 2;

  // 2) DHT11 (max ~1 read/s; our loop is 2 s), sound, flame/humidity analog
  float tC = dht.readTemperature(), h = dht.readHumidity();
  if (!isnan(tC)) tempC = tC;
  if (!isnan(h)) humPct = h;
  float snd = soundLevel();
  float flameLevel = 100.0f - analogAvg(PIN_FLAME_AO) * 100.0f / 4095.0f;   // AO falls as IR rises
  // Require analog IR confirmation (>20%) so an untuned or inverted digital pin does not cause false alarms
  bool flame = (flameHits >= 2 && flameLevel > 20.0f) || (flameLevel > 45.0f);
  float humRaw = HAS_ANALOG_HUMIDITY ? analogAvg(PIN_HUM_AO) : NAN;
  if (!isnan(humRaw)) moistPct = constrain((MOIST_DRY - humRaw) * 100.0f / (MOIST_DRY - MOIST_WET), 0.0f, 100.0f);

  // 3) time-domain features
  float rx = meanRemove(ax), ry = meanRemove(ay), rz = meanRemove(az);
  float comb = sqrt(rx * rx + ry * ry + rz * rz);
  float peak = 0; double m4 = 0, m2 = 0;
  for (int i = 0; i < N; i++) {
    float mag = sqrt(ax[i] * ax[i] + ay[i] * ay[i] + az[i] * az[i]);
    peak = max(peak, max(fabsf(ax[i]), max(fabsf(ay[i]), fabsf(az[i]))));
    m2 += mag * mag; m4 += (double)mag * mag * mag * mag;
  }
  float crest = peak / (comb + 1e-9f);
  float kurt = (m2 > 0) ? (m4 / N) / ((m2 / N) * (m2 / N)) : 0;

  // 4) FFT on radial X + 0.5 * axial Z, top-5 peaks
  static float spec[N / 2];
  for (int i = 0; i < N; i++) { vReal[i] = ax[i]; vImag[i] = 0; }
  FFT.windowing(FFTWindow::Hann, FFTDirection::Forward);
  FFT.compute(FFTDirection::Forward);
  FFT.complexToMagnitude();
  for (int i = 0; i < N / 2; i++) spec[i] = vReal[i] * 4.0f / N;
  for (int i = 0; i < N; i++) { vReal[i] = az[i]; vImag[i] = 0; }
  FFT.windowing(FFTWindow::Hann, FFTDirection::Forward);
  FFT.compute(FFTDirection::Forward);
  FFT.complexToMagnitude();
  for (int i = 0; i < N / 2; i++) spec[i] += 0.5f * vReal[i] * 4.0f / N;
  spec[0] = spec[1] = spec[2] = 0;
  float pkHz[5] = {0}, pkAmp[5] = {0}; int found = 0;
  for (int k = 0; k < 5; k++) {
    int best = -1; float bv = max(0.001f, 0.2f * comb);
    for (int i = 3; i < N / 2; i++) {
      float hz = i * FS / N; bool near = false;
      for (int j = 0; j < found; j++) if (fabsf(hz - pkHz[j]) < 3) near = true;
      if (!near && spec[i] > bv) { bv = spec[i]; best = i; }
    }
    if (best < 0) break;
    pkHz[found] = best * FS / N; pkAmp[found] = bv; found++;
  }

  // 5) baseline + alert logic
  const char* status = "OK"; String reason = ""; float z = NAN;
  if (!baselineReady) {
    learnCount++;
    double d = comb - bMean; bMean += d / learnCount; bM2 += d * (comb - bMean);
    if (!isnan(tempC)) bTemp += (tempC - bTemp) / learnCount;
    if (!isnan(snd)) bSound += (snd - bSound) / learnCount;
    status = "LEARNING";
    if (learnCount >= LEARN_WINDOWS) baselineReady = true;
  } else {
    float sd = max((float)sqrt(bM2 / max(1, learnCount - 1)), 0.15f * (float)bMean);
    z = hasMpu && sd > 0 ? (comb - bMean) / sd : NAN;
    float dT = isnan(tempC) ? 0 : tempC - bTemp;
    overCount = (!isnan(z) && z > Z_ALERT) ? overCount + 1 : 0;
    if (overCount >= 3 || dT > DT_ALERT) {
      status = "ALERT";
      if (overCount >= 3) reason += "Vibration " + String(comb / bMean, 1) + "x baseline RMS (z=" + String(z, 1) +
                                    "); dominant " + String(pkHz[0], 1) + " Hz (" + String(pkHz[0] / (RPM_HINT / 60.0), 2) + "x)";
      if (dT > DT_ALERT) reason += (reason.length() ? "; " : "") + String("temperature +") + String(dT, 1) + " C over baseline";
    } else if ((!isnan(z) && z > Z_WARN) || dT > DT_WARN) {
      status = "WARN"; reason = "z=" + String(z, 1) + ", dT=" + String(dT, 1) + " C";
    }
  }
  if (!strcmp(status, "OK") && !isnan(humPct) && humPct > HUM_WARN) { status = "WARN"; reason = "Humidity " + String(humPct, 0) + "% (condensation risk)"; }
  if (comb > ABS_ALERT_G) {
    status = "ALERT";
    reason = "Vibration " + String(comb, 2) + " g RMS exceeds absolute limit" + (reason.length() ? "; " + reason : "");
  }
  if (flame) {
    status = "ALERT";
    reason = "FLAME DETECTED near machine" + (reason.length() ? "; " + reason : "");
  }

  // 6) local alarm
  if (HAS_BUZZER) {
    if (flame) tone(PIN_BUZZER, 3000, 600);
    else if (!strcmp(status, "ALERT")) tone(PIN_BUZZER, 2200, 150);
  }

  // 7) JSON payload
  JsonDocument doc;
  doc["node_id"] = NODE_ID;
  String ts = isoNow(); if (ts.length()) doc["ts"] = ts;
  doc["status"] = status;
  if (reason.length()) doc["reason"] = reason;
  if (hasMpu) {
  JsonObject vib = doc["vib"].to<JsonObject>();
  JsonObject rms = vib["rms_g"].to<JsonObject>();
  rms["x"] = rx; rms["y"] = ry; rms["z"] = rz;
  vib["peak_g"] = peak; vib["crest"] = crest; vib["kurtosis"] = kurt;
  JsonArray pk = vib["fft_peaks"].to<JsonArray>();
  for (int i = 0; i < found; i++) { JsonObject p = pk.add<JsonObject>(); p["hz"] = pkHz[i]; p["amp"] = pkAmp[i]; }
  if (baselineReady) { vib["baseline_rms"] = bMean; vib["zscore"] = z; }
  }
  if (baselineReady) {
    doc["temp_baseline_c"] = bTemp; if (HAS_SOUND) doc["sound_baseline"] = bSound;
  }
  if (!isnan(tempC)) doc["temp_c"] = tempC;
  if (!isnan(humPct)) doc["humidity_pct"] = humPct;
  if (!isnan(humRaw)) { doc["humidity_raw"] = humRaw; doc["moisture_pct"] = moistPct; }
  if (!isnan(snd)) doc["sound_level"] = snd;
  doc["sound_event"] = soundEvent;
  doc["flame"] = flame;
  doc["flame_level"] = flameLevel;
  doc["rpm_hint"] = RPM_HINT;
  doc["fw"] = hasMpu ? "aurasense-esp32-1.2" : "aurasense-esp32-1.2 (no MPU6050)";
  doc["buffered"] = false;
  String body; serializeJson(doc, body);

  bool posted = postJson(body);
  if (posted) flushBuffer(); else bufferPush(body);
  showLcd(status, comb, z, found ? pkHz[0] : 0, snd, flame, posted, reason);
  Serial.printf("%s rms=%.3f z=%.1f T=%.1f H=%.0f snd=%.0f flame=%d peaks=%d buf=%d\n",
                status, comb, isnan(z) ? 0 : z, tempC, humPct, snd, flame, found, bufCount);

  int32_t wait = POST_INTERVAL_MS - (millis() - loopStart);
  if (wait > 0) delay(wait);
}
