from urllib.parse import urlparse
import json
import logging
import paho.mqtt.client
import secrets
import ssl
import threading


def parse_mqtt_url(url):
    url_data = urlparse(url)
    use_tls = url_data.scheme in ["wss", "mqtts"]
    use_ws = url_data.scheme in ["ws", "wss"]

    if not url_data.port:
        port = 443 if use_tls else 80
    else:
        port = url_data.port

    transport = "websockets" if use_ws else "tcp"
    return (url_data.hostname, port, url_data.path, transport, use_ws, use_tls)


def get_client(url, user, password, client_id, user_data=None):
    (host, port, path, transport, use_ws, use_tls) = parse_mqtt_url(url)
    client = paho.mqtt.client.Client(paho.mqtt.client.CallbackAPIVersion.VERSION1, client_id=f"{client_id}-{secrets.token_hex(4)}", transport=transport)
    if use_tls:
        client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
    if use_ws:
        client.ws_set_options(path=path)
    client.username_pw_set(user, password)
    client.user_data_set(user_data)
    client.connect(host, port)
    return client


class MqttSyncClient:
    def __init__(self, url, user, password, client_id):
        self.__logger = logging.getLogger("MQTT")
        self.__client = get_client(url, user, password, client_id, self)
        self.__client.on_message = MqttSyncClient.__on_message
        self.__client.on_connect = MqttSyncClient.__on_connect
        self.__client.on_disconnect = MqttSyncClient.__on_disconnect
        self.__event = threading.Event()
        self.__response_topic = None
        self.__response_data = None

    def subscribe(self, *args, **kwargs):
        self.__client.subscribe(*args, **kwargs)

    def unsubscribe(self, *args, **kwargs):
        self.__client.unsubscribe(*args, **kwargs)

    def publish(self, *args, **kwargs):
        self.__client.publish(*args, **kwargs)

    def get_message(self, timeout=5):
        if self.__event.wait(timeout=timeout):
            self.__event.clear()
            return (self.__response_topic, self.__response_data)
        else:
            return (None, None)

    def send_and_get(self, publish_topic, subscribe_topic, message=None):
        self.__client.subscribe(subscribe_topic)
        self.__client.publish(publish_topic, message)
        (topic, data) = self.get_message()
        self.__client.unsubscribe(subscribe_topic)
        return data

    def __on_message(client, user_data, message):
        self = user_data
        self.__response_topic = message.topic
        self.__response_data = message.payload.decode("utf-8")
        self.__event.set()

    def __on_connect(client, user_data, flags, rc):
        self = user_data
        self.__logger.info("connected")

    def __on_disconnect(client, user_data, flags):
        self = user_data
        self.__logger.info("disconnected")

    def start(self):
        self.__client.loop_start()

    def stop(self):
        self.__client.loop_stop()
        self.__client.disconnect()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
