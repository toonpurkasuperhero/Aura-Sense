/*
 * AuraSense hardware self-test
 * ----------------------------
 * Flash this BEFORE the real firmware. Every 2 s it prints a PASS / FAIL / WAIT report
 * for each part and cycles the results on the LCD:
 *
 *   I2C bus   finds MPU6050 (0x68/0x69) and the LCD backpack (0x27/0x3F)
 *   MPU6050   WHO_AM_I + gravity check (|a| ~ 1 g) + live vibration RMS ("tap the sensor")
 *   DHT11     temperature + humidity readable
 *   FLAME     DO trips at least once            -> show it a lighter flame
 *   SOUND     DO trips / AO swings at least once -> clap near the microphone
 *   HUMIDITY  analog module AO is not stuck at 0 or 4095
 *   WIFI      joins the network
 *   BACKEND   GET <BACKEND_URL>/api/health answers 200 (laptop reachable, firewall open)
 *
 * Uses the same pins and config.h as aurasense_node.
 */
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <DHT.h>
#include <LiquidCrystal_I2C.h>

#if __has_include("config.h")
#include "config.h"
#endif
#ifndef CFG_WIFI_SSID
#define CFG_WIFI_SSID   "YOUR_WIFI_SSID"
#define CFG_WIFI_PASS   "YOUR_WIFI_PASSWORD"
#define CFG_BACKEND_URL "http://192.168.1.100:8000"
#endif

const bool FLAME_ACTIVE_LOW = true;
const bool SOUND_ACTIVE_LOW = false;
const bool HAS_SOUND = true;   // sound module wired
const int PIN_SDA = 21, PIN_SCL = 22, PIN_DHT = 4;
const int PIN_SOUND_AO = 32, PIN_FLAME_AO = 35, PIN_HUM_AO = 34, PIN_FLAME_DO = 23, PIN_SOUND_DO = 18;

DHT dht(PIN_DHT, DHT11);
LiquidCrystal_I2C* lcd = nullptr;
uint8_t mpuAddr = 0, lcdAddr = 0;
bool flameSeen = false, soundSeen = false, backendOk = false;
int soundMinAo = 4095, soundMaxAo = 0;
String backendMsg = "not tried";
uint32_t lastNet = 0;
int page = 0;

bool present(uint8_t a) { Wire.beginTransmission(a); return Wire.endTransmission() == 0; }

uint8_t rd(uint8_t addr, uint8_t reg) {
  Wire.beginTransmission(addr); Wire.write(reg); Wire.endTransmission(false);
  Wire.requestFrom(addr, (uint8_t)1); return Wire.available() ? Wire.read() : 0xFF;
}

void accel(float& x, float& y, float& z) {
  Wire.beginTransmission(mpuAddr); Wire.write(0x3B); Wire.endTransmission(false);
  Wire.requestFrom(mpuAddr, (uint8_t)6);
  int16_t rx = (Wire.read() << 8) | Wire.read(), ry = (Wire.read() << 8) | Wire.read(), rz = (Wire.read() << 8) | Wire.read();
  x = rx / 8192.0f; y = ry / 8192.0f; z = rz / 8192.0f;
}

void lcdShow(String a, String b) {
  if (!lcd) return;
  while (a.length() < 16) a += ' ';
  while (b.length() < 16) b += ' ';
  lcd->setCursor(0, 0); lcd->print(a.substring(0, 16));
  lcd->setCursor(0, 1); lcd->print(b.substring(0, 16));
}

void checkNetwork() {
  if (millis() - lastNet < 10000 && lastNet) return;
  lastNet = millis();
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.mode(WIFI_STA); WiFi.begin(CFG_WIFI_SSID, CFG_WIFI_PASS);
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < 8000) delay(200);
  }
  if (WiFi.status() != WL_CONNECTED) { backendOk = false; backendMsg = "no WiFi"; return; }
  HTTPClient http;
  http.setTimeout(3000);
  http.begin(String(CFG_BACKEND_URL) + "/api/health");
  int code = http.GET();
  http.end();
  backendOk = code == 200;
  backendMsg = code > 0 ? "HTTP " + String(code) : "unreachable (" + String(code) + ")";
}

void setup() {
  Serial.begin(115200);
  delay(500);
  pinMode(PIN_FLAME_DO, INPUT); pinMode(PIN_SOUND_DO, INPUT);
  analogReadResolution(12); analogSetAttenuation(ADC_11db);
  Wire.begin(PIN_SDA, PIN_SCL, 100000);
  lcdAddr = present(0x27) ? 0x27 : present(0x3F) ? 0x3F : 0;
  if (lcdAddr) { lcd = new LiquidCrystal_I2C(lcdAddr, 16, 2); lcd->init(); lcd->backlight(); lcdShow("AuraSense", "Self-test..."); }
  mpuAddr = present(0x68) ? 0x68 : present(0x69) ? 0x69 : 0;
  if (mpuAddr) { Wire.beginTransmission(mpuAddr); Wire.write(0x6B); Wire.write(0); Wire.endTransmission();
                 Wire.beginTransmission(mpuAddr); Wire.write(0x1C); Wire.write(0x08); Wire.endTransmission(); }
  dht.begin();
  Serial.println("\n=== AuraSense hardware self-test ===");
  Serial.print("I2C devices found:");
  for (uint8_t a = 1; a < 127; a++) if (present(a)) Serial.printf(" 0x%02X", a);
  Serial.println();
}

void loop() {
  // --- watch flame / sound for ~1.5 s while sampling vibration
  float sx = 0, sy = 0, sz = 0, sxx = 0, syy = 0, szz = 0, gsum = 0; int n = 0;
  uint32_t t0 = millis();
  while (millis() - t0 < 1500) {
    if (digitalRead(PIN_FLAME_DO) == (FLAME_ACTIVE_LOW ? LOW : HIGH)) flameSeen = true;
    if (HAS_SOUND) {
      if (digitalRead(PIN_SOUND_DO) == (SOUND_ACTIVE_LOW ? LOW : HIGH)) soundSeen = true;
      int ao = analogRead(PIN_SOUND_AO); soundMinAo = min(soundMinAo, ao); soundMaxAo = max(soundMaxAo, ao);
    }
    if (mpuAddr) {
      float x, y, z; accel(x, y, z);
      sx += x; sy += y; sz += z; sxx += x * x; syy += y * y; szz += z * z; gsum += sqrt(x * x + y * y + z * z); n++;
    }
    delay(2);
  }
  if (HAS_SOUND && soundMaxAo - soundMinAo > 600) soundSeen = true;   // a clap swings the AO strongly

  // --- MPU6050
  String mpu = "FAIL not found on I2C (check SDA21/SCL22, 3V3)";
  bool mpuOk = false; float rms = 0, g = 0;
  if (mpuAddr && n) {
    uint8_t who = rd(mpuAddr, 0x75);
    g = gsum / n;
    rms = sqrt(max(0.0f, (sxx / n - sq(sx / n)) + (syy / n - sq(sy / n)) + (szz / n - sq(sz / n))));
    mpuOk = g > 0.8 && g < 1.2;
    mpu = String(mpuOk ? "PASS" : "FAIL") + " who=0x" + String(who, HEX) + " |a|=" + String(g, 2) + "g vibRMS=" + String(rms, 3) + "g";
  }
  // --- DHT11
  float t = dht.readTemperature(), h = dht.readHumidity();
  bool dhtOk = !isnan(t) && !isnan(h);
  String dhtS = dhtOk ? "PASS " + String(t, 0) + "C " + String(h, 0) + "%RH" : "FAIL no reading (DATA->GPIO4, 3V3)";
  // --- analogs
  int flameAo = analogRead(PIN_FLAME_AO), humAo = analogRead(PIN_HUM_AO);
  bool humOk = humAo > 20 && humAo < 4075;
  // --- network
  checkNetwork();

  Serial.println("------------------------------------------------------------");
  Serial.printf("I2C      %s  (MPU %s, LCD %s)\n", mpuAddr && lcdAddr ? "PASS" : "CHECK",
                mpuAddr ? String("0x" + String(mpuAddr, HEX)).c_str() : "missing", lcdAddr ? String("0x" + String(lcdAddr, HEX)).c_str() : "missing");
  Serial.printf("MPU6050  %s\n", mpu.c_str());
  Serial.printf("DHT11    %s\n", dhtS.c_str());
  Serial.printf("FLAME    %s  DO=%d AO=%d\n", flameSeen ? "PASS (tripped)" : "WAIT show a flame / lighter", digitalRead(PIN_FLAME_DO), flameAo);
  if (HAS_SOUND) Serial.printf("SOUND    %s  AO swing=%d\n", soundSeen ? "PASS (tripped)" : "WAIT clap near the mic", soundMaxAo - soundMinAo);
  else Serial.println("SOUND    skipped (not wired)");
  Serial.printf("MOISTURE %s  AO=%d (4095 = dry air, lower = wetter)\n", humOk ? "PASS" : "CHECK (stuck at 0/4095? dry probe reads 4095)", humAo);
  Serial.printf("WIFI     %s  %s  RSSI %d\n", WiFi.status() == WL_CONNECTED ? "PASS" : "FAIL", WiFi.localIP().toString().c_str(), WiFi.RSSI());
  Serial.printf("BACKEND  %s  %s -> %s\n", backendOk ? "PASS" : "FAIL", CFG_BACKEND_URL, backendMsg.c_str());

  switch (page++ % 6) {
    case 0: lcdShow(String("MPU ") + (mpuOk ? "OK " : "FAIL ") + String(g, 2) + "g", "vib " + String(rms, 3) + "g"); break;
    case 1: lcdShow(String("DHT11 ") + (dhtOk ? "OK" : "FAIL"), dhtOk ? String(t, 0) + "C  " + String(h, 0) + "%RH" : "check GPIO4"); break;
    case 2: lcdShow(String("FLAME ") + (flameSeen ? "OK" : "show fire"), "AO " + String(flameAo)); break;
    case 3: lcdShow("MOISTURE AO", String(humAo)); break;
    case 4: lcdShow(String("WIFI ") + (WiFi.status() == WL_CONNECTED ? "OK" : "FAIL"), WiFi.localIP().toString()); break;
    default: lcdShow(String("BACKEND ") + (backendOk ? "OK" : "FAIL"), backendMsg);
  }
  soundMinAo = 4095; soundMaxAo = 0;
}
