// Copyright 2026 The Blitzen Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
//
// Blitzen M0 display client — a THIN HUB75 panel client.
//
// Adafruit Feather M0 WiFi (SAMD21 + ATWINC1500) + RGB Matrix FeatherWing -> 32x32 panel.
// Generality lives in the host (see led_control_design.md section 2); this firmware only:
//   * joins WiFi (WiFi101 / ATWINC1500 -- NOT WiFiNINA),
//   * receives live frames over DDP and renders them (preempting any loop),
//   * stores host-uploaded 16-color frames in a RAM slot ring and plays them untethered,
//   * answers a tiny control protocol (store/play/stop/clear/info/config).
//
// Wire protocol constants MUST match host/protocol.py and host/transports/ddp.py.
//
// !!! ON-HARDWARE TODO: this sketch is written to the protocols but has NOT been compiled
// !!! or run on a board in this environment. Build it, read the free-RAM print at boot,
// !!! and record the number (and resulting slot capacity) in README.md before relying on
// !!! the slot ring. See README.md for the build/flash steps and pinned library versions.

#include <Adafruit_Protomatter.h>
#include <WiFi101.h>
#include <WiFiUdp.h>

#include "config.h"

// ---------------------------------------------------------------------------------------
// Panel geometry and encoding sizes. Change these together if you use a different panel.
// ---------------------------------------------------------------------------------------
#define PANEL_W 32
#define PANEL_H 32

// Measured on real hardware: at 32x32, Protomatter dominates SRAM (~16 KB at BIT_DEPTH 4,
// double-buffered), which leaves only a few slot-ring frames on the 32 KB SAMD21. Both are
// overridable from the build (e.g. -DBIT_DEPTH=3 / -DDOUBLE_BUFFER=false) to trade color
// depth / tear-free updates for more standalone-loop frames.
#ifndef BIT_DEPTH
#define BIT_DEPTH 3  // measured: 11-frame loop, tear-free, 512 colors on this 32x32 panel
#endif
#ifndef DOUBLE_BUFFER
#define DOUBLE_BUFFER true
#endif

static const uint16_t NUM_PIXELS = PANEL_W * PANEL_H;            // 1024
static const uint16_t IDX16_BYTES = NUM_PIXELS / 2;             // 512  (two 4-bit idx/byte)
static const uint16_t PALETTE_BYTES = 16 * 3;                   // 48
static const uint16_t BYTES_PER_SLOT = IDX16_BYTES + PALETTE_BYTES;  // 560

// ---------------------------------------------------------------------------------------
// RGB Matrix FeatherWing pin map for Feather M0/M4 (per Adafruit's Protomatter examples).
// VERIFY against the Adafruit_Protomatter "simple" example for your FeatherWing revision.
// ---------------------------------------------------------------------------------------
uint8_t rgbPins[] = {6, 5, 9, 11, 10, 12};
uint8_t addrPins[] = {A5, A4, A3, A2};  // 4 address lines -> 32 rows
uint8_t clockPin = 13;
uint8_t latchPin = 0;
uint8_t oePin = 1;

Adafruit_Protomatter matrix(PANEL_W, BIT_DEPTH, 1, rgbPins, 4, addrPins, clockPin, latchPin,
                            oePin, /*doubleBuffer=*/DOUBLE_BUFFER);

// ---------------------------------------------------------------------------------------
// ATWINC1500 control pins for the Adafruit Feather M0 WiFi.
// ---------------------------------------------------------------------------------------
#define WINC_CS 8
#define WINC_IRQ 7
#define WINC_RST 4
#define WINC_EN 2

WiFiUDP ddpUdp;
WiFiUDP ctrlUdp;

// ---------------------------------------------------------------------------------------
// Protocol constants (mirror host/protocol.py and host/transports/ddp.py).
// ---------------------------------------------------------------------------------------
static const uint8_t DDP_FLAG_PUSH = 0x01;

enum {
  OP_STORE = 0x01,
  OP_PLAY = 0x02,
  OP_STOP = 0x03,
  OP_CLEAR = 0x04,
  OP_INFO = 0x05,
  OP_CONFIG = 0x06,
};
static const uint8_t ACK_FLAG = 0x80;
static const uint8_t STATUS_OK = 0x00;
static const uint8_t STATUS_ERR = 0x01;

enum { ENC_RAW = 0, ENC_RGB565 = 1, ENC_IDX16 = 2, ENC_IDX256 = 3, ENC_BIT1 = 4 };
enum { RESUME_IDLE = 0, RESUME_EXPLICIT = 1 };

// ---------------------------------------------------------------------------------------
// Slot ring + playback state. Capacity is computed at boot from MEASURED free RAM, not
// hardcoded (design spec section 5.1 / open question 1).
// ---------------------------------------------------------------------------------------
uint8_t *slotData = nullptr;    // maxSlots * BYTES_PER_SLOT  (palette then packed indices)
uint16_t *slotDwell = nullptr;  // per-slot dwell, ms
bool *slotUsed = nullptr;
int maxSlots = 0;
int freeRamAtBoot = 0;

bool loopActive = false;
int loopStart = 0, loopEnd = 0;
int loopRepeat = 0, loopCount = 0, loopPos = 0;
unsigned long lastSlotMillis = 0;

bool liveMode = false;            // a live DDP frame is currently driving the panel
unsigned long lastDdpMillis = 0;
uint8_t resumePolicy = RESUME_IDLE;
uint16_t idleMs = 2000;

// Control RX buffer big enough for the largest STORE: 2 hdr + 1 slot + 2 dwell + 1 enc +
// 1 palcount + 48 palette + 512 payload = 567.
static uint8_t ctrlBuf[600];

// ---------------------------------------------------------------------------------------
// Free-RAM estimate for SAMD21 (gap between the stack and the top of the heap).
// ---------------------------------------------------------------------------------------
extern "C" char *sbrk(int incr);
int freeRam() {
  char top;
  return &top - reinterpret_cast<char *>(sbrk(0));
}

static inline uint16_t color565(uint8_t r, uint8_t g, uint8_t b) {
  return matrix.color565(r, g, b);
}

// ---------------------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  // Do not block forever on the USB serial monitor; give it a brief moment.
  unsigned long serialWait = millis();
  while (!Serial && millis() - serialWait < 2000) {
  }

  Serial.print("free RAM at boot (bytes): ");
  Serial.println(freeRam());

  ProtomatterStatus status = matrix.begin();
  Serial.print("Protomatter begin status: ");
  Serial.println((int)status);
  Serial.print("free RAM after Protomatter (bytes): ");
  Serial.println(freeRam());

  WiFi.setPins(WINC_CS, WINC_IRQ, WINC_RST, WINC_EN);
  Serial.print("Joining WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) {
    delay(500);
    Serial.print('.');
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    IPAddress ip = WiFi.localIP();
    Serial.print("IP: ");
    Serial.print(ip[0]);
    Serial.print('.');
    Serial.print(ip[1]);
    Serial.print('.');
    Serial.print(ip[2]);
    Serial.print('.');
    Serial.println(ip[3]);
  } else {
    Serial.println("WiFi NOT connected (will keep retrying in background)");
  }

  ddpUdp.begin(DDP_PORT_CFG);
  ctrlUdp.begin(CTRL_PORT_CFG);

  // ---- size the slot ring from measured free RAM ----
  freeRamAtBoot = freeRam();
  Serial.print("free RAM after init (bytes): ");
  Serial.println(freeRamAtBoot);  // <-- ON-HARDWARE TODO: record this in README.md

  // Headroom left free above the slot pool for stack growth. Must cover WiFi101's UDP
  // RX path, which is deep: with a 1024 margin, freeRam() went NEGATIVE during an INFO
  // request on real hardware (stack/heap near-collision). 4096 keeps ~2.7 KB free under
  // load on this build. Measured, not guessed.
  const int margin = 4096;
  long pool = (long)freeRamAtBoot - margin;
  int perSlot = BYTES_PER_SLOT + (int)sizeof(uint16_t) + (int)sizeof(bool);
  maxSlots = (pool > 0) ? (int)(pool / perSlot) : 0;
  if (maxSlots > 0) {
    slotData = (uint8_t *)malloc((size_t)maxSlots * BYTES_PER_SLOT);
    slotDwell = (uint16_t *)malloc((size_t)maxSlots * sizeof(uint16_t));
    slotUsed = (bool *)malloc((size_t)maxSlots * sizeof(bool));
    if (!slotData || !slotDwell || !slotUsed) {
      maxSlots = 0;  // allocation failed; disable the ring rather than crash
    } else {
      for (int i = 0; i < maxSlots; i++) slotUsed[i] = false;
    }
  }
  Serial.print("slot capacity (frames): ");
  Serial.println(maxSlots);  // <-- ON-HARDWARE TODO: record this in README.md
}

// ---------------------------------------------------------------------------------------
void loop() {
  handleDdp();
  handleControl();

  // Loop-resume policy after live frames stop (design spec open question 5).
  if (liveMode && resumePolicy == RESUME_IDLE && (millis() - lastDdpMillis > idleMs)) {
    liveMode = false;
  }

  if (!liveMode) {
    if (loopActive) {
      advanceLoop();
    } else {
      showFallback();
    }
  }
}

// ---------------------------------------------------------------------------------------
// DDP live receive. Reads the 10-byte header, then streams the payload straight into the
// matrix back-buffer pixel-by-pixel (no 3072-byte intermediate). Renders on the PUSH bit.
// Assumes pixel-aligned chunks (offset and length multiples of 3), which the host's
// DDPTransport guarantees (max_payload is a multiple of 3).
// ---------------------------------------------------------------------------------------
void handleDdp() {
  int packetSize = ddpUdp.parsePacket();
  if (packetSize < 10) {
    if (packetSize > 0) ddpUdp.flush();
    return;
  }

  uint8_t header[10];
  ddpUdp.read(header, 10);
  uint8_t flags = header[0];
  uint32_t offset = ((uint32_t)header[4] << 24) | ((uint32_t)header[5] << 16) |
                    ((uint32_t)header[6] << 8) | (uint32_t)header[7];
  uint16_t length = ((uint16_t)header[8] << 8) | (uint16_t)header[9];

  liveMode = true;
  lastDdpMillis = millis();

  uint32_t pixel = offset / 3;
  uint8_t buf[192];  // up to 64 pixels per read
  uint16_t remaining = length;
  while (remaining > 0) {
    int want = remaining < sizeof(buf) ? remaining : sizeof(buf);
    int got = ddpUdp.read(buf, want);
    if (got <= 0) break;
    for (int i = 0; i + 2 < got; i += 3) {
      int x = pixel % PANEL_W;
      int y = pixel / PANEL_W;
      if (y < PANEL_H) matrix.drawPixel(x, y, color565(buf[i], buf[i + 1], buf[i + 2]));
      pixel++;
    }
    remaining -= got;
  }

  if (flags & DDP_FLAG_PUSH) {
    matrix.show();
  }
}

// ---------------------------------------------------------------------------------------
// Control protocol. Each request is [opcode][seq][body]; we reply [opcode|0x80][seq][status].
// ---------------------------------------------------------------------------------------
void handleControl() {
  int packetSize = ctrlUdp.parsePacket();
  if (packetSize < 2) {
    if (packetSize > 0) ctrlUdp.flush();
    return;
  }
  int n = ctrlUdp.read(ctrlBuf, sizeof(ctrlBuf));
  if (n < 2) return;

  uint8_t op = ctrlBuf[0];
  uint8_t seq = ctrlBuf[1];

  switch (op) {
    case OP_STORE:
      handleStore(seq, ctrlBuf + 2, n - 2);
      break;
    case OP_PLAY:
      handlePlay(seq, ctrlBuf + 2, n - 2);
      break;
    case OP_STOP:
      loopActive = false;
      sendAck(op, seq, STATUS_OK, nullptr, 0);
      break;
    case OP_CLEAR:
      loopActive = false;
      for (int i = 0; i < maxSlots; i++) slotUsed[i] = false;
      sendAck(op, seq, STATUS_OK, nullptr, 0);
      break;
    case OP_INFO:
      handleInfo(seq);
      break;
    case OP_CONFIG:
      handleConfig(seq, ctrlBuf + 2, n - 2);
      break;
    default:
      sendAck(op, seq, STATUS_ERR, nullptr, 0);
      break;
  }
}

// body: [slot][dwell_hi][dwell_lo][encoding][palette_count][palette...][payload...]
void handleStore(uint8_t seq, uint8_t *body, int len) {
  if (len < 5) {
    sendAck(OP_STORE, seq, STATUS_ERR, nullptr, 0);
    return;
  }
  uint8_t slot = body[0];
  uint16_t dwell = ((uint16_t)body[1] << 8) | body[2];
  uint8_t encoding = body[3];
  uint8_t palCount = body[4];
  uint8_t *palette = body + 5;
  int palBytes = palCount * 3;
  uint8_t *payload = palette + palBytes;
  int payloadLen = len - 5 - palBytes;

  bool ok = (slot < maxSlots) && (encoding == ENC_IDX16) && (palCount == 16) &&
            (payloadLen >= IDX16_BYTES);
  if (!ok) {
    sendAck(OP_STORE, seq, STATUS_ERR, nullptr, 0);
    return;
  }
  uint8_t *dest = slotData + (size_t)slot * BYTES_PER_SLOT;
  memcpy(dest, palette, PALETTE_BYTES);
  memcpy(dest + PALETTE_BYTES, payload, IDX16_BYTES);
  slotDwell[slot] = dwell;
  slotUsed[slot] = true;
  sendAck(OP_STORE, seq, STATUS_OK, nullptr, 0);
}

// body: [start][end][repeat_hi][repeat_lo]
void handlePlay(uint8_t seq, uint8_t *body, int len) {
  if (len < 4) {
    sendAck(OP_PLAY, seq, STATUS_ERR, nullptr, 0);
    return;
  }
  loopStart = body[0];
  loopEnd = body[1];
  loopRepeat = ((uint16_t)body[2] << 8) | body[3];
  if (loopStart >= maxSlots || loopEnd >= maxSlots || loopStart > loopEnd) {
    sendAck(OP_PLAY, seq, STATUS_ERR, nullptr, 0);
    return;
  }
  loopPos = loopStart;
  loopCount = 0;
  loopActive = true;
  liveMode = false;
  lastSlotMillis = 0;  // render the first frame immediately
  sendAck(OP_PLAY, seq, STATUS_OK, nullptr, 0);
}

// reply body: [free_ram:4 BE][slot_capacity:1][slots_used:1]
void handleInfo(uint8_t seq) {
  int used = 0;
  for (int i = 0; i < maxSlots; i++)
    if (slotUsed[i]) used++;
  uint32_t freeNow = (uint32_t)freeRam();
  uint8_t body[6];
  body[0] = (freeNow >> 24) & 0xFF;
  body[1] = (freeNow >> 16) & 0xFF;
  body[2] = (freeNow >> 8) & 0xFF;
  body[3] = freeNow & 0xFF;
  body[4] = (uint8_t)(maxSlots & 0xFF);
  body[5] = (uint8_t)(used & 0xFF);
  sendAck(OP_INFO, seq, STATUS_OK, body, sizeof(body));
}

// body: [resume_policy][idle_ms_hi][idle_ms_lo]
void handleConfig(uint8_t seq, uint8_t *body, int len) {
  if (len < 3) {
    sendAck(OP_CONFIG, seq, STATUS_ERR, nullptr, 0);
    return;
  }
  resumePolicy = body[0];
  idleMs = ((uint16_t)body[1] << 8) | body[2];
  sendAck(OP_CONFIG, seq, STATUS_OK, nullptr, 0);
}

void sendAck(uint8_t op, uint8_t seq, uint8_t status, const uint8_t *body, int bodyLen) {
  uint8_t reply[3 + 16];
  reply[0] = op | ACK_FLAG;
  reply[1] = seq;
  reply[2] = status;
  int total = 3;
  if (body && bodyLen > 0 && bodyLen <= 16) {
    memcpy(reply + 3, body, bodyLen);
    total += bodyLen;
  }
  ctrlUdp.beginPacket(ctrlUdp.remoteIP(), ctrlUdp.remotePort());
  ctrlUdp.write(reply, total);
  ctrlUdp.endPacket();
}

// ---------------------------------------------------------------------------------------
// Standalone loop: walk used slots honoring per-frame dwell.
// ---------------------------------------------------------------------------------------
void advanceLoop() {
  unsigned long now = millis();
  if (loopPos < loopStart || loopPos > loopEnd) loopPos = loopStart;

  uint16_t dwell = slotUsed[loopPos] ? slotDwell[loopPos] : 0;
  if (lastSlotMillis != 0 && (now - lastSlotMillis) < dwell) return;

  if (slotUsed[loopPos]) {
    drawSlot(loopPos);
    matrix.show();
  }
  lastSlotMillis = now;

  loopPos++;
  if (loopPos > loopEnd) {
    loopPos = loopStart;
    loopCount++;
    if (loopRepeat > 0 && loopCount >= loopRepeat) loopActive = false;
  }
}

void drawSlot(int slot) {
  uint8_t *base = slotData + (size_t)slot * BYTES_PER_SLOT;
  uint8_t *palette = base;
  uint8_t *indices = base + PALETTE_BYTES;
  for (int p = 0; p < NUM_PIXELS; p++) {
    uint8_t packed = indices[p >> 1];
    uint8_t ci = (p & 1) ? (packed & 0x0F) : (packed >> 4);
    uint8_t *c = palette + ci * 3;
    matrix.drawPixel(p % PANEL_W, p / PANEL_W, color565(c[0], c[1], c[2]));
  }
}

// ---------------------------------------------------------------------------------------
// Baked fallback for the disconnected / nothing-stored state: a slow diagonal rainbow so
// the panel is never dark (design spec section 5.3).
// ---------------------------------------------------------------------------------------
void showFallback() {
  static unsigned long last = 0;
  unsigned long now = millis();
  if (now - last < 50) return;  // ~20 fps
  last = now;

  uint8_t phase = (now / 16) & 0xFF;
  for (int y = 0; y < PANEL_H; y++) {
    for (int x = 0; x < PANEL_W; x++) {
      uint8_t hue = (uint8_t)((x + y) * 4 + phase);
      matrix.drawPixel(x, y, wheel(hue));
    }
  }
  matrix.show();
}

// Classic color wheel: 0..255 -> 565.
uint16_t wheel(uint8_t pos) {
  pos = 255 - pos;
  if (pos < 85) return color565(255 - pos * 3, 0, pos * 3);
  if (pos < 170) {
    pos -= 85;
    return color565(0, pos * 3, 255 - pos * 3);
  }
  pos -= 170;
  return color565(pos * 3, 255 - pos * 3, 0);
}
