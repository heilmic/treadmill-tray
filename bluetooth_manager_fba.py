"""
BLE-Manager für den fba0-Service des PitPat Laufbands.
Kein Wrapper-Protokoll – Pakete werden direkt geschrieben.
"""

import asyncio
import logging
from bleak import BleakClient
from bleak.exc import BleakError
from threading import Thread, Lock, Event

from treadmill_data import TreadmillData

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

SERVICE_UUID = "0000fba0-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID  = "0000fba2-0000-1000-8000-00805f9b34fb"
WRITE_UUID   = "0000fba1-0000-1000-8000-00805f9b34fb"
HEARTBEAT    = bytes([0x6a, 0x05, 0xfd, 0xf8, 0x43])


class BluetoothManagerFBA:
    """BLE-Manager für den fba0-Service (kein Protokoll-Wrapper)."""

    class _Request:
        def __init__(self, data: bytes):
            self.data    = data
            self.event   = Event()
            self.success = False

    def __init__(self, device_address: str, on_disconnect=None, on_receive=None):
        self.device_address = device_address
        self.on_disconnect  = on_disconnect
        self.on_receive     = on_receive

        self._pending: BluetoothManagerFBA._Request | None = None
        self._lock = Lock()

        self.client = BleakClient(
            device_address,
            disconnected_callback=self._on_ble_disconnect,
        )
        self.loop   = asyncio.new_event_loop()
        self.thread = Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    # ------------------------------------------------------------------
    # Event-Loop
    # ------------------------------------------------------------------

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _schedule(self, coro):
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    # ------------------------------------------------------------------
    # Verbindung
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        try:
            f = asyncio.run_coroutine_threadsafe(self.client.connect(), self.loop)
            f.result(timeout=15)
            if self.client.is_connected:
                self._schedule(
                    self.client.start_notify(NOTIFY_UUID, self._notification_handler)
                )
                logging.info(f"Connected (fba) to {self.device_address}")
                return True
            logging.error("connect() returned but is_connected is False")
            return False
        except Exception as e:
            logging.error(f"Connect error: {e}")
            return False

    def disconnect(self) -> bool:
        try:
            if self.client.is_connected:
                f = asyncio.run_coroutine_threadsafe(
                    self.client.disconnect(), self.loop
                )
                f.result(timeout=10)
            return True
        except Exception as e:
            logging.error(f"Disconnect error: {e}")
            return False

    def is_connected(self) -> bool:
        return self.client.is_connected

    def shutdown(self):
        try:
            if self.client.is_connected:
                self.disconnect()
        except Exception as exc:
            logging.warning(f"Shutdown disconnect warning: {exc}")
        try:
            if self.loop.is_running():
                self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=5)
        except Exception as exc:
            logging.warning(f"Shutdown loop warning: {exc}")

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _on_ble_disconnect(self, client):
        logging.warning(f"Disconnected: {self.device_address}")
        if self.on_disconnect:
            self.loop.call_soon_threadsafe(self.on_disconnect, self.device_address)

    def _notification_handler(self, sender: str, data: bytearray):
        hex_str = data.hex()
        logging.info(f"Notification ({len(data)} bytes): {hex_str}")

        # fba-Service: kein 4-Byte-Header; ignore_checksum weil die
        # Prüfsumme ggf. ein anderes Format nutzt als der ff-Service.
        parsed = TreadmillData(bytes(data), ignore_checksum=True)
        if self.on_receive:
            self.loop.call_soon_threadsafe(self.on_receive, parsed)

        self._schedule(self._send_next())

    async def _send_next(self):
        """Sendet den nächsten ausstehenden Befehl oder einen Heartbeat."""
        with self._lock:
            req = self._pending
            self._pending = None

        if req:
            try:
                await self.client.write_gatt_char(WRITE_UUID, req.data, response=True)
                logging.info(f"Command sent: {req.data.hex()}")
                req.success = True
            except Exception as e:
                logging.error(f"Write error: {e}")
                req.success = False
            finally:
                req.event.set()
        else:
            try:
                await self.client.write_gatt_char(WRITE_UUID, HEARTBEAT, response=True)
                logging.debug("Heartbeat sent")
            except Exception as e:
                logging.error(f"Heartbeat error: {e}")

    # ------------------------------------------------------------------
    # Befehle senden
    # ------------------------------------------------------------------

    def send_data(self, data: bytes, timeout: float = 10.0) -> bool:
        req = self._Request(data)
        with self._lock:
            if self._pending and not self._pending.event.is_set():
                # Vorherigen Befehl verwerfen
                self._pending.success = False
                self._pending.event.set()
            self._pending = req
            logging.info(f"Data queued: {data.hex()}")

        ok = req.event.wait(timeout=timeout)
        if not ok:
            logging.error("Timeout waiting for command send")
        return ok and req.success
