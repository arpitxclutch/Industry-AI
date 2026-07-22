/*
  Intelligent Industrial Safety and Predictive Risk Monitoring System
  ESP32 Firmware

  Reads the gas, temperature/humidity, flame, and PIR-motion inputs every
  2 seconds and publishes them as one JSON message to
  factory/section1/sensors. Listens on factory/section1/control for
  {"led":"green|yellow|red","buzzer":bool,"relay":bool} commands sent back
  by risk_engine.py and drives the LEDs, buzzer, and relay accordingly.

  Same pin numbers and topic names are used in the Wokwi simulation
  (diagram.json) and in the real hardware build (see the build guide,
  Section 4.2).
*/

#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <ArduinoJson.h>

// ---------------- Wi-Fi ----------------
const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASSWORD = "";

// ---------------- MQTT ----------------
const char* MQTT_BROKER = "test.mosquitto.org";
const int   MQTT_PORT = 1883;
const char* TOPIC_SENSORS = "factory/section1/sensors";
const char* TOPIC_CONTROL = "factory/section1/control";

WiFiClient espClient;
PubSubClient mqttClient(espClient);

// ---------------- Pin map ----------------
#define PIN_DHT       15
#define PIN_GAS       34   // analog, MQ-2 (potentiometer in simulation)
#define PIN_FLAME     27   // digital, active LOW
#define PIN_PIR       26   // digital, active HIGH
#define PIN_LED_GREEN 32
#define PIN_LED_YELLOW 14
#define PIN_LED_RED   12
#define PIN_RELAY     25
#define PIN_BUZZER    33

#define DHTTYPE DHT22
DHT dht(PIN_DHT, DHTTYPE);

const unsigned long PUBLISH_INTERVAL_MS = 2000;
unsigned long lastPublish = 0;

// ---------------- Wi-Fi + MQTT connection ----------------
void connectWiFi() {
  Serial.print("Connecting to WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();
  Serial.println("WiFi connected");
  Serial.println(WiFi.localIP());
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) {
    Serial.println("Failed to parse control message");
    return;
  }

  const char* led = doc["led"] | "green";
  bool buzzerOn = doc["buzzer"] | false;
  bool relayOn = doc["relay"] | true;

  digitalWrite(PIN_LED_GREEN, LOW);
  digitalWrite(PIN_LED_YELLOW, LOW);
  digitalWrite(PIN_LED_RED, LOW);

  if (strcmp(led, "green") == 0) {
    digitalWrite(PIN_LED_GREEN, HIGH);
  } else if (strcmp(led, "yellow") == 0) {
    digitalWrite(PIN_LED_YELLOW, HIGH);
  } else if (strcmp(led, "red") == 0) {
    digitalWrite(PIN_LED_RED, HIGH);
  }

  digitalWrite(PIN_BUZZER, buzzerOn ? HIGH : LOW);
  // relay == true means "keep equipment running"; relay == false de-energises it
  digitalWrite(PIN_RELAY, relayOn ? HIGH : LOW);
}

void connectMQTT() {
  while (!mqttClient.connected()) {
    Serial.print("Connecting to MQTT broker...");
    String clientId = "esp32-section1-" + String(random(0xffff), HEX);
    if (mqttClient.connect(clientId.c_str())) {
      Serial.println("connected");
      mqttClient.subscribe(TOPIC_CONTROL);
    } else {
      Serial.print("failed, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" retrying in 2s");
      delay(2000);
    }
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(PIN_FLAME, INPUT_PULLUP);   // button pulls LOW when pressed = flame detected
  pinMode(PIN_PIR, INPUT_PULLDOWN);   // button pulls HIGH when pressed = motion detected
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_RELAY, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);

  digitalWrite(PIN_LED_GREEN, HIGH);  // boot in a safe/idle GREEN state
  digitalWrite(PIN_RELAY, HIGH);      // equipment energised by default

  dht.begin();
  connectWiFi();

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }
  if (!mqttClient.connected()) {
    connectMQTT();
  }
  mqttClient.loop();

  unsigned long now = millis();
  if (now - lastPublish >= PUBLISH_INTERVAL_MS) {
    lastPublish = now;

    float humidity = dht.readHumidity();
    float temperature = dht.readTemperature();
    if (isnan(humidity) || isnan(temperature)) {
      humidity = 0.0;
      temperature = 0.0;
    }

    int rawGas = analogRead(PIN_GAS);              // 0-4095
    int gasPpm = map(rawGas, 0, 4095, 0, 1000);     // scaled to an approximate ppm range

    bool flame = (digitalRead(PIN_FLAME) == LOW);
    bool motion = (digitalRead(PIN_PIR) == HIGH);

    StaticJsonDocument<256> doc;
    doc["gas_ppm"] = gasPpm;
    doc["temperature"] = temperature;
    doc["humidity"] = humidity;
    doc["flame"] = flame;
    doc["motion"] = motion;

    char buffer[256];
    size_t n = serializeJson(doc, buffer);
    mqttClient.publish(TOPIC_SENSORS, buffer, n);

    Serial.print("Published: ");
    Serial.println(buffer);
  }
}
