# BLE / HEX command reference

This document summarizes the currently known BLE identifiers and command packets used by `treadmill-tray`.

## BLE UUIDs

### Service

- `0000fba0-0000-1000-8000-00805f9b34fb`

### Write characteristic

- `0000fba1-0000-1000-8000-00805f9b34fb`

### Notify characteristic

- `0000fba2-0000-1000-8000-00805f9b34fb`

## Packet format (control packets)

Most treadmill control packets built by `treadmill_controller.py` are 23 bytes:

- Start byte: `0x6A`
- Length: `0x17`
- End byte: `0x43`
- Checksum: XOR over bytes 1..20

## Known command types

- `0x00` = stop
- `0x02` = pause
- `0x04` = start / set speed

## Verified special packets

### Sound ON / unmute

```text
6a17f1000000000000000000000000000000000001e743
```

### Sound OFF / mute

```text
6a17f1000000000000000000100000000000000001f743
```

These two packets were verified against a real Bluetooth capture.

## Heartbeat

```text
6a05fdf843
```

## Example control packets

These examples come from the current packet generator defaults in `treadmill_controller.py`.

### Start at 1.0 km/h

```text
6a170000000003e801005000040000000dba9d76ef1a43
```

### Set speed to 1.2 km/h

```text
6a170000000004b005005000040000000dba9d76ef4143
```

### Pause

```text
6a1700000000000001005000020000000dba9d76eff743
```

### Stop

```text
6a1700000000000001005000000000000dba9d76eff543
```

## Notes

- The app uses metric mode (`km/h`) by default.
- Speed values are encoded as integer units where `1000 = 1.0 km/h`.
- Direct UI presets currently cover `1` to `6` km/h.
- Fine adjustment uses `±0.1 km/h` steps.

## Source files

- `treadmill_controller.py`
- `bluetooth_manager_fba.py`
- `treadmill_data.py`
