#include <WiFi.h>
#include <WebSocketsClient.h>
#include <driver/i2s.h>

// ====== Wi-Fi credentials ======
const char* ssid = "Airtel_LocalHost";
const char* password = "spidylala";

// ====== Server details ======
const char* serverHost = "192.168.1.2";  // <-- Replace with your PC/Laptop IP
const int serverPort = 8080;
const char* serverPath = "/ws";

// ====== I2S Mic Pins (INMP441) ======
#define I2S_WS   25   // LRCL
#define I2S_SD   34   // DOUT
#define I2S_SCK  26   // BCLK

// ====== Globals ======
WebSocketsClient webSocket;
bool recording = false;

// ====== I2S Init ======
void i2sInit() {
  const i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = 16000,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 256,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };

  const i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = -1,
    .data_in_num = I2S_SD
  };

  i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pin_config);
}

// ====== WebSocket Events ======
void onWebSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch (type) {
    case WStype_DISCONNECTED:
      Serial.println("❌ WebSocket Disconnected!");
      recording = false;
      break;

    case WStype_CONNECTED:
      Serial.println("✅ Connected to WebSocket server");
      break;

    case WStype_TEXT: {
      String msg = String((char*)payload);
      Serial.print("📩 Message from server: ");
      Serial.println(msg);

      if (msg == "START") {
        recording = true;
        Serial.println("🎤 Recording started");
      } else if (msg == "STOP") {
        recording = false;
        Serial.println("⏹️ Recording stopped");
      }
      break;
    }

    default:
      break;
  }
}

// ====== Setup ======
void setup() {
  Serial.begin(115200);
  delay(1000);

  // Connect Wi-Fi
  Serial.printf("Connecting to Wi-Fi: %s\n", ssid);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\n✅ Wi-Fi Connected. ESP32 IP: %s\n", WiFi.localIP().toString().c_str());

  // Connect WebSocket
  webSocket.begin(serverHost, serverPort, serverPath);
  webSocket.onEvent(onWebSocketEvent);

  // Init I2S
  i2sInit();
}

// ====== Main Loop ======
void loop() {
  webSocket.loop();

  if (recording) {
    int16_t buffer[512];
    size_t bytes_read = 0;

    esp_err_t result = i2s_read(I2S_NUM_0, buffer, sizeof(buffer), &bytes_read, portMAX_DELAY);

    if (result == ESP_OK && bytes_read > 0) {
      webSocket.sendBIN((uint8_t*)buffer, bytes_read);
      Serial.printf("📤 Sent %d bytes\n", bytes_read);
    }
  }
}
