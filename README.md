# Hcalory HBU1S BLE Control for Home Assistant

A Home Assistant custom integration for controlling Hcalory HBU1S 5KW diesel heaters via Bluetooth Low Energy.

## Features

- **Power control** - turn the heater on and off
- **Temperature mode** - thermostat control with a target temperature (8-36°C); turning on always lands in temperature mode at the requested target, even if the heater was last used in gear mode
- **Gear mode** - choose the "Gear" preset to run at a fixed output level (the heater's last-used level)
- **Room temperature** - the heater's own ambient reading, in °C whatever units the heater displays
- **Heater status** - starting / running / cooling down (shown as heating / fan in Home Assistant), plus body temperature, supply voltage, auto start/stop and display units as attributes
- **Voice assistants and HomeKit** - "set the heater to 18 degrees" turns it on at 18°C in one go
- **Bluetooth auto-discovery** - discovers heaters advertising as "Heater*"
- **Robust connections** - uses Home Assistant's recommended Bluetooth connection handling, so it works through any adapter or Bluetooth proxy with a free connection slot and reconnects cleanly

## Installation

### HACS (Recommended)

1. Add this repository as a custom repository in HACS
2. Search for "Hcalory HBU1S"
3. Install and restart Home Assistant

### Manual Installation

1. Download the latest release
2. Extract `custom_components/hcalory_hbu1s` to your HA `config/custom_components/` folder
3. Restart Home Assistant

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for "Hcalory"
3. Select your heater from the discovered devices
4. Done!

## Using it

The heater appears as a climate entity:

| Action | What happens |
|---|---|
| HVAC mode **Heat** / turn on | Powers on, switches to temperature mode, sends the target temperature |
| Set temperature | While on: switches to temperature mode if needed and sets the target. While off: stored and used next time it is turned on |
| Preset **Gear** | Powers on (if needed) in gear mode at the last-used gear level |
| Preset **Temperature** | Powers on (if needed) in temperature mode at the current target |
| HVAC mode **Off** | Powers off; the heater then runs its fan to cool down (HVAC action "fan") before going to standby |

While the heater is off, the preset shows the mode it will resume in.

## Supported Devices

- Hcalory HBU1S 5KW Diesel Heater (Bluetooth only models)

Other Hcalory Bluetooth heaters may work but are untested.

## Protocol Documentation

This integration was built by reverse-engineering the Bluetooth protocol from the official Hcalory app (Android HCI snoop logs of the app in use).

### BLE Service/Characteristics

| UUID | Description |
|------|-------------|
| `0000bd39-...` | Primary service |
| `0000bdf8-...` | Commands (write without response) **and** status (notify). The official app writes all commands here |
| `0000bdf7-...` | Write-only; not used by the official app |

### Commands

Every command is `00 02 00 01 00 01 00` + `[length]` + `[body]` + `[checksum]`, where length = body length + 1 and checksum = sum of the body bytes & 0xFF.

**Action commands** - body `04 00 00 09` + eight `00` bytes + `[action]`:

| Action | Code | Notes |
|---|---|---|
| Status query | `00` | Also keeps the connection alive |
| Power off | `01` | Heater then cools down with the fan running |
| Power on | `02` | Heater resumes in the mode it was last used in |
| Auto start/stop | `05` | Toggles |
| Temperature mode | `06` | Only accepted while the heater is on |
| Gear mode | `07` | Only accepted while the heater is on |

**Other commands** (body shown):

| Command | Body | Notes |
|---|---|---|
| Init | `0c 00 00 05 01 00 00 00 00` | Sent after connecting |
| Set temperature | `06 00 00 02 [temp] [unit]` | `temp` in display units; `unit` 01 = °F, 00 = °C |
| Set gear level | `07 00 00 01 [level]` | Not used by the integration yet |
| Display units | `0b 00 00 02 02 [unit]` | 01 = °F, 00 = °C. Versions before 0.3.0 sent this after power on, believing it selected temperature mode |

The app also sends the current time (`0a 00 00 05 [hh] [mm] [ss] 07 00` every few seconds); the heater works without it.

### Status notifications

43-byte notifications, message type `0x23` at byte 7:

| Byte(s) | Meaning |
|---|---|
| 20 | Run state: `00` standby; `80`, `81`, `83` starting; `85` (`87`) running; `4x` cooling down after switch-off |
| 21 | Mode while on: `01` temperature, `02` gear (`00` in standby) |
| 22 | Target temperature (display units) in temperature mode, or gear level in gear mode |
| 23 | Auto start/stop: `01` on, `02` off |
| 24-25 | Supply voltage, tenths of a volt |
| 27-28 | Heater body temperature, signed tenths of a degree in display units |
| 30-31 | Ambient (room) temperature, signed tenths of a degree in display units |
| 37 | Display units: `01` °F, `00` °C |
| 42 | Checksum |

## Known Limitations

1. **Sub-zero ambient** - the ambient value is treated as a signed number; this hasn't been confirmed with a real reading below 0°C yet
2. **Gear level** - gear mode runs at the heater's last-used level; the level can't be changed from Home Assistant yet
3. **Auto start/stop** - shown as an attribute but not controllable yet
4. **Single connection** - the heater accepts one Bluetooth connection and stops advertising while connected. Close the Hcalory app (or disable the integration) to use the app, and vice versa
5. **Range** - the heater must be within Bluetooth range of a Home Assistant adapter or Bluetooth proxy

## Troubleshooting

### Heater not discovered / "not found"
- Ensure the heater is powered
- Check Bluetooth is enabled on your Home Assistant host
- Fully close the official Hcalory app: while it is connected the heater does not advertise, and Home Assistant keeps retrying until it does

### Commands not working
- Ensure the official Hcalory app is disconnected
- Check the Home Assistant logs for connection errors

## Development

Protocol analysis was performed using:
- nRF Connect for BLE exploration
- Android HCI snoop logs of the official app, decoded to match each app action with the bytes sent and the status changes
- Manual testing and verification

## License

MIT License

## Credits

Built for van life automation 🚐
