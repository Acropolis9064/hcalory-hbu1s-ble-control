# Hcalory HBU1S BLE Control for Home Assistant

A Home Assistant custom integration for controlling Hcalory HBU1S 5KW diesel heaters via Bluetooth Low Energy.

## Features

- **Power Control** - Turn heater on/off
- **Temperature Control** - Set target temperature (8-36°C)
- **Climate Entity** - Standard HA climate integration with Heat/Off modes
- **Bluetooth Auto-Discovery** - Automatically discovers heaters named "Heater*"

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

## Supported Devices

- Hcalory HBU1S 5KW Diesel Heater (Bluetooth only models)

Other Hcalory Bluetooth heaters may work but are untested.

## Protocol Documentation

This integration was built by reverse-engineering the Bluetooth protocol from the official Hcalory app.

### BLE Service/Characteristics

| UUID | Description |
|------|-------------|
| `0000bd39-...` | Primary Service |
| `0000bdf7-...` | Write Characteristic (commands) |
| `0000bdf5-...` | Notify Characteristic (status) |

### Commands

All commands use wrapper: `00 02 00 01 00 01 00 [length] [payload] [checksum]`

| Command | Payload |
|---------|---------|
| Power ON | `0e 04 00 00 09 00 00 00 00 00 00 00 00 02 0f` |
| Power OFF | `0e 04 00 00 09 00 00 00 00 00 00 00 00 01 0e` |
| Set Temp | `06 00 00 02 [TEMP_HEX] 00 [CHECKSUM]` |

Temperature checksum = `(06 + 00 + 00 + 02 + temp + 00) & 0xFF`

## Known Limitations

1. **Status parsing** - Reading ambient/body temperature from notifications needs refinement
2. **Single connection** - Only one BLE device can connect at a time (close the Hcalory app first)
3. **Range** - Requires Home Assistant host to be within BLE range (~10m)

## Troubleshooting

### Heater not discovered
- Ensure heater is powered on
- Check Bluetooth is enabled on your Home Assistant host
- Close the official Hcalory app (it may be holding the connection)

### Commands not working
- Ensure the official Hcalory app is disconnected
- Check HA logs for connection errors

## Development

Protocol analysis was performed using:
- nRF Connect for BLE exploration
- Android HCI snoop logs for command capture
- Manual testing and verification

## License

MIT License

## Credits

Built for van life automation 🚐
