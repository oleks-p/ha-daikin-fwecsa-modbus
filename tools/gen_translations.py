#!/usr/bin/env python3
"""Write strings.json and translations/{en,uk}.json from one table.

English and Ukrainian sit side by side here, so a string cannot be added to one
language and forgotten in the other, and strings.json and en.json stay equal.
A test fails if the committed files fall behind this script, or if an entity
has no name here.

    .venv/bin/python tools/gen_translations.py            # rewrite the three files
    .venv/bin/python tools/gen_translations.py --check    # exit 1 if any is stale
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "custom_components" / "daikin_fwecsa_modbus"

FAN_SPEED_STATES = {
    "extra_low": ("Extra low", "Наднизька"),
    "low": ("Low", "Низька"),
    "medium": ("Medium", "Середня"),
    "high": ("High", "Висока"),
    "auto": ("Auto", "Авто"),
}
MODE_STATES = {
    "heating": ("Heating", "Опалення"),
    "cooling": ("Cooling", "Охолодження"),
}
VALVE_STATES = {
    "on": ("Open", "Відкрито"),
    "off": ("Closed", "Закрито"),
}
FAN_STATUS_STATES = {
    "off": ("Off", "Вимкнено"),
    **{k: v for k, v in FAN_SPEED_STATES.items() if k != "auto"},
}

# Holding registers: the same names on the sensor, number and select platforms.
HOLDING = {
    "cooling_setpoint": ("Cooling setpoint", "Уставка охолодження"),
    "cooling_setpoint_min": ("Cooling setpoint minimum", "Мінімум уставки охолодження"),
    "cooling_setpoint_max": ("Cooling setpoint maximum", "Максимум уставки охолодження"),
    "heating_setpoint": ("Heating setpoint", "Уставка опалення"),
    "heating_setpoint_min": ("Heating setpoint minimum", "Мінімум уставки опалення"),
    "heating_setpoint_max": ("Heating setpoint maximum", "Максимум уставки опалення"),
    "single_setpoint": ("Single setpoint", "Єдина уставка"),
    "humidity_setpoint": ("Humidity setpoint", "Уставка вологості"),
    "humidity_setpoint_min": ("Humidity setpoint minimum", "Мінімум уставки вологості"),
    "humidity_setpoint_max": ("Humidity setpoint maximum", "Максимум уставки вологості"),
    "fan_speed": ("Fan speed", "Швидкість вентилятора", FAN_SPEED_STATES),
    "modulating_fan_speed": ("Modulating fan speed", "Швидкість модульованого вентилятора"),
}

# key: (en, uk[, {state: (en, uk)}])
SENSOR = {
    "room_temperature": ("Room temperature", "Температура в приміщенні"),
    "room_humidity": ("Room humidity", "Вологість у приміщенні"),
    "water_temperature": ("Water temperature", "Температура води"),
    "hot_water_temperature": ("Hot water temperature", "Температура гарячої води"),
    "fan_status": ("Fan", "Вентилятор", FAN_STATUS_STATES),
    "modulating_fan_output": ("Modulating fan output", "Вихід модульованого вентилятора"),
    "analog_output_1": ("Analog output 1", "Аналоговий вихід 1"),
    "analog_output_2": ("Analog output 2", "Аналоговий вихід 2"),
    "analog_output_3": ("Analog output 3", "Аналоговий вихід 3"),
    "active_setpoint": ("Setpoint in use", "Активна уставка"),
    "cooling_setpoint_status": ("Cooling setpoint (status)", "Уставка охолодження (стан)"),
    "heating_setpoint_status": ("Heating setpoint (status)", "Уставка опалення (стан)"),
    "single_setpoint_status": ("Single setpoint (status)", "Єдина уставка (стан)"),
    "active_humidity_setpoint": ("Humidity setpoint in use", "Активна уставка вологості"),
    "valve_type": ("Valve type", "Тип клапана", {
        "none": ("None", "Немає"),
        "on_off": ("On/off", "Двопозиційний"),
        "modulating": ("Modulating", "Модулюючий"),
    }),
    "mode_in_use": ("Mode in use", "Режим у роботі", MODE_STATES),
    "mode": ("Mode (command)", "Режим (команда)", MODE_STATES),
    **HOLDING,
    "last_successful_read": ("Last successful read", "Останнє успішне зчитування"),
    "read_failures": ("Read failures", "Помилки зчитування"),
}

DISCRETE = {
    "unit_on": ("Unit on", "Блок увімкнено"),
    "economy_on": ("Economy active", "Економ активний"),
    "anti_freeze_on": ("Anti-freeze active", "Антизамерзання активне"),
    "alarm": ("Alarm", "Аварія"),
    "room_probe_alarm": ("Room probe alarm", "Аварія датчика приміщення"),
    "water_probe_alarm": ("Water probe alarm", "Аварія датчика води"),
    "hot_water_probe_alarm": ("Hot water probe alarm", "Аварія датчика гарячої води"),
    "humidity_probe_alarm": ("Humidity probe alarm", "Аварія датчика вологості"),
    "four_speeds": ("Four-speed unit", "Чотиришвидкісний блок"),
    "four_pipes": ("Four-pipe unit", "Чотиритрубний блок"),
    "modulating_fan": ("Modulating fan", "Модульований вентилятор"),
    "board_probe": ("Air probe on the board", "Датчик повітря на платі"),
    "heaters_installed": ("Electric heaters fitted", "Електронагрівачі встановлено"),
    "humidity_probe_installed": ("Humidity probe fitted", "Датчик вологості встановлено"),
    **{f"output_{n}": (f"Output O{n}", f"Вихід O{n}") for n in range(1, 8)},
    "water_probe_present": ("Water probe fitted", "Датчик води встановлено"),
    "hot_water_probe_present": ("Hot water probe fitted", "Датчик гарячої води встановлено"),
    "dehumidifying": ("Dehumidifying", "Осушення"),
    "valve_open": ("Valve", "Клапан", VALVE_STATES),
    "off_by_contact": ("Off by remote contact", "Вимкнено віддаленим контактом"),
    "fan_auto_mode": ("Automatic fan", "Автоматичний вентилятор"),
    "heater_on": ("Heater", "Нагрівач"),
    "valve_present": ("Valve fitted", "Клапан встановлено"),
    "economy_by_contact": ("Economy from contact", "Економ від контакту"),
}

COIL = {
    "power": ("Power", "Живлення"),
    "economy": ("Economy", "Економ"),
    "anti_freeze": ("Anti-freeze", "Антизамерзання"),
    "electric_heater": ("Electric heater", "Електронагрівач"),
    "modulating_fan_auto": ("Modulating fan auto", "Авто модульованого вентилятора"),
    "master_power": ("On/off from master", "Увімкнення від майстра"),
    "master_economy": ("Economy from master", "Економ від майстра"),
    "master_mode": ("Mode from master", "Режим від майстра"),
    "master_anti_freeze": ("Anti-freeze from master", "Антизамерзання від майстра"),
    "master_electric_heater": ("Electric heaters from master", "Електронагрівачі від майстра"),
    "master_setpoint": ("Setpoint from master", "Уставка від майстра"),
    "master_setpoint_limits": ("Setpoint limits from master", "Межі уставки від майстра"),
    "master_fan_speed": ("Fan speed from master", "Швидкість вентилятора від майстра"),
    "keyboard_lock": ("Keyboard lock", "Блокування клавіатури"),
    "master_humidity": ("Humidity control from master", "Контроль вологості від майстра"),
    "humidity_control": ("Humidity control", "Контроль вологості"),
    "output_7_command": ("Output O7", "Вихід O7"),
}

BINARY_SENSOR = {
    **DISCRETE,
    # The coils, read-only: named as the command they are.
    **{key: (f"{en} (command)", f"{uk} (команда)") for key, (en, uk) in COIL.items()},
}

NUMBER = {key: v for key, v in HOLDING.items() if key != "fan_speed"}
SELECT = {"mode": ("Mode", "Режим", MODE_STATES), "fan_speed": HOLDING["fan_speed"]}

PREFIX_HELP = (
    "Every entity id starts with it, e.g. climate.fancoil and "
    "sensor.fancoil_room_temperature.",
    "З нього починається кожен ідентифікатор сутності, наприклад climate.fancoil і "
    "sensor.fancoil_room_temperature.",
)
SLAVE_HELP = (
    "Set on the unit: PRG → Networks and connections (password 20) → SETUP RS485 → Serial "
    "address. MST/SLV must be \"Slave from SPV\" and Protocol \"Modbus\".",
    "Задається на блоці: PRG → Мережі та з'єднання (пароль 20) → SETUP RS485 → Серійна "
    "адреса. MST/SLV має бути \"Slave from SPV\", протокол — \"Modbus\".",
)
SERIAL_DESC = (
    "Terminals A/B/GND on the I/O board, 8N1. Prefer a /dev/serial/by-id path: it survives "
    "reboots and replugging. Use a network gateway instead if anything else polls this bus.",
    "Клеми A/B/GND на платі вводу-виводу, 8N1. Краще шлях /dev/serial/by-id: він не "
    "змінюється після перезавантаження. Якщо цю шину опитує ще щось, використайте мережевий "
    "шлюз.",
)
NETWORK_DESC = (
    "A Modbus gateway on the fancoil's RS-485 bus. mbusd and most gateways speak Modbus TCP; "
    "choose RTU over TCP only for a transparent serial server.",
    "Шлюз Modbus на шині RS-485 фанкойла. mbusd і більшість шлюзів працюють як Modbus TCP; "
    "RTU over TCP — лише для прозорого послідовного сервера.",
)
SERIAL_DATA = {
    "serial_port": ("Serial port", "Послідовний порт"),
    "baudrate": ("Baud rate", "Швидкість"),
    "slave": ("Modbus address", "Адреса Modbus"),
}
NETWORK_DATA = {
    "host": ("Host", "Хост"),
    "port": ("Port", "Порт"),
    "transport": ("Gateway type", "Тип шлюзу"),
    "slave": ("Modbus address", "Адреса Modbus"),
}
PREFIX = {"entity_prefix": ("Entity ID prefix", "Префікс ідентифікаторів сутностей")}
MENU = {
    "network": ("Network gateway (e.g. mbusd)", "Мережевий шлюз (напр. mbusd)"),
    "serial": ("USB / RS-485 adapter", "Адаптер USB / RS-485"),
}

ERRORS = {
    "cannot_connect": (
        "No answer from the unit. Check the address and baud rate, and that the unit is "
        "powered and set to \"Slave from SPV\".",
        "Блок не відповідає. Перевірте адресу й швидкість, живлення блока і що він "
        "налаштований як \"Slave from SPV\".",
    ),
    "not_fwecsa": (
        "Something answered at that address, but not like an FWECSA.",
        "За цією адресою щось відповіло, але не як FWECSA.",
    ),
    "invalid_prefix": (
        "Use lowercase letters, digits and underscores only.",
        "Лише малі латинські літери, цифри та підкреслення.",
    ),
    "prefix_in_use": (
        "Another fancoil already uses this prefix.",
        "Цей префікс уже використовує інший фанкойл.",
    ),
}

EXCEPTIONS = {
    "writes_disabled": (
        "Writes are off for this fancoil. Turn on \"Allow writes\" in its options first.",
        "Запис для цього фанкойла вимкнено. Спершу увімкніть \"Дозволити запис\" у параметрах.",
    ),
    "not_writable": ("{key} cannot be written.", "{key} не можна записати."),
    "out_of_range": (
        "{value} is outside {minimum} to {maximum} in steps of {step} for {key}.",
        "{value} поза межами від {minimum} до {maximum} з кроком {step} для {key}.",
    ),
    "rate_limited": (
        "Too many writes: {key} can be written once every {interval} s, and the unit {daily} "
        "times a day.",
        "Забагато записів: {key} можна записувати раз на {interval} с, а блок — {daily} разів "
        "на добу.",
    ),
    "write_not_applied": (
        "The fancoil did not apply {key}: wrote {expected}, it reads {actual}.",
        "Фанкойл не застосував {key}: записано {expected}, зчитано {actual}.",
    ),
    "write_not_applied_consent": (
        "The fancoil did not apply {key}: wrote {expected}, it reads {actual}. {consent} is off; "
        "the unit may take {key} from Modbus only with it on.",
        "Фанкойл не застосував {key}: записано {expected}, зчитано {actual}. {consent} вимкнено; "
        "блок може приймати {key} через Modbus лише з ним увімкненим.",
    ),
    "write_failed": (
        "No answer from the fancoil while writing: {error}",
        "Фанкойл не відповів під час запису: {error}",
    ),
    "write_refused": (
        "The fancoil refused the write (Modbus exception {code}).",
        "Фанкойл відхилив запис (виняток Modbus {code}).",
    ),
    "read_failed": (
        "No answer from the fancoil while reading: {error}",
        "Фанкойл не відповів під час зчитування: {error}",
    ),
    "choose_entry": (
        "Choose which fancoil: none or more than one is loaded.",
        "Оберіть фанкойл: не завантажено жодного або більше одного.",
    ),
    "cannot_connect": (
        "No answer from the FWECSA at {endpoint}.",
        "FWECSA за адресою {endpoint} не відповідає.",
    ),
    "not_fwecsa": (
        "Modbus address {slave} does not answer like an FWECSA.",
        "Адреса Modbus {slave} відповідає не як FWECSA.",
    ),
    "no_season": (
        "The unit has not reported heating or cooling yet, so it is not known which setpoint "
        "to write.",
        "Блок ще не повідомив опалення чи охолодження, тож невідомо, яку уставку записувати.",
    ),
    "hvac_mode_unavailable": (
        "{mode} is not available with the unit's summer/winter switching as set in the options.",
        "Режим {mode} недоступний за перемиканням літо/зима, вказаним у параметрах.",
    ),
    "fan_mode_unavailable": (
        "Fan speed {mode} is not available on this unit.",
        "Швидкість вентилятора {mode} недоступна на цьому блоці.",
    ),
}


def _entities(table: dict, lang: int) -> dict:
    out = {}
    for key, row in table.items():
        entry: dict = {"name": row[lang]}
        if len(row) > 2:
            entry["state"] = {s: names[lang] for s, names in row[2].items()}
        out[key] = entry
    return out


def _fields(table: dict, lang: int) -> dict:
    return {key: pair[lang] for key, pair in table.items()}


def build(lang: int) -> dict:
    """lang: 0 = English, 1 = Ukrainian."""
    def t(en: str, uk: str) -> str:
        return (en, uk)[lang]

    serial_form = {
        "title": t("RS-485 adapter", "Адаптер RS-485"),
        "description": SERIAL_DESC[lang],
        "data": _fields({**SERIAL_DATA, **PREFIX}, lang),
        "data_description": {"slave": SLAVE_HELP[lang], "entity_prefix": PREFIX_HELP[lang]},
    }
    network_form = {
        "title": t("Network gateway", "Мережевий шлюз"),
        "description": NETWORK_DESC[lang],
        "data": _fields({**NETWORK_DATA, **PREFIX}, lang),
        "data_description": {"slave": SLAVE_HELP[lang], "entity_prefix": PREFIX_HELP[lang]},
    }

    def without_prefix(form: dict) -> dict:
        return {**form,
                "data": {k: v for k, v in form["data"].items() if k != "entity_prefix"},
                "data_description": {"slave": SLAVE_HELP[lang]}}

    return {
        "config": {
            "step": {
                "user": {
                    "title": t("How is the fancoil connected?", "Як під'єднано фанкойл?"),
                    "description": t(
                        "The integration reads the unit. Writes stay off unless you turn them "
                        "on in its options. RS-485 allows one master: if the heat pump or a "
                        "wall panel shares this bus, put a gateway such as mbusd in front of it "
                        "and connect every integration through the gateway.",
                        "Інтеграція зчитує блок. Запис вимкнено, доки ви не ввімкнете його в "
                        "параметрах. На RS-485 може бути лише один майстер: якщо цю шину "
                        "ділять тепловий насос чи настінна панель, поставте шлюз (напр. mbusd) "
                        "і під'єднуйте всі інтеграції через нього."),
                    "menu_options": _fields(MENU, lang),
                },
                "serial": serial_form,
                "network": network_form,
                "reconfigure": {
                    "title": t("Change the connection", "Змінити з'єднання"),
                    "description": t("Same unit, different link. Entity ids and history are "
                                     "kept.",
                                     "Той самий блок, інше з'єднання. Ідентифікатори та історія "
                                     "сутностей зберігаються."),
                    "menu_options": {f"reconfigure_{k}": v[lang] for k, v in MENU.items()},
                },
                "reconfigure_serial": without_prefix(serial_form),
                "reconfigure_network": without_prefix(network_form),
            },
            "error": _fields(ERRORS, lang),
            "abort": {
                "already_configured": t("This fancoil is already configured.",
                                        "Цей фанкойл уже налаштовано."),
                "reconfigure_successful": t("The connection was changed.",
                                            "З'єднання змінено."),
            },
        },
        "options": {
            "step": {
                "init": {
                    "title": t("Fancoil options", "Параметри фанкойла"),
                    "data": {
                        "unavailable_after": t("Unavailable after", "Недоступний через"),
                        "allow_writes": t("Allow writes", "Дозволити запис"),
                        "switching": t("Summer/winter switching on the unit",
                                       "Перемикання літо/зима на блоці"),
                    },
                    "data_description": {
                        "unavailable_after": t(
                            "How long the link may fail before entities show as unavailable. "
                            "The last values are shown until then.",
                            "Скільки часу зв'язок може не працювати, перш ніж сутності стануть "
                            "недоступними. До того показуються останні значення."),
                        "allow_writes": t(
                            "Off: read only. On: the coils and holding registers become "
                            "switches, numbers and a select, and the climate entity can switch "
                            "the unit and set its target. Every write is read back.",
                            "Вимкнено: лише зчитування. Увімкнено: котушки та регістри "
                            "зберігання стають перемикачами, числами й списком, а клімат може "
                            "вмикати блок і задавати уставку. Кожен запис перевіряється "
                            "зчитуванням."),
                        "switching": t(
                            "Must match the unit's parameter \"Switching Summer/Winter\" "
                            "(PRG → configuration menu, password 10). It decides which "
                            "setpoint the climate entity writes and whether it can choose "
                            "heating or cooling.",
                            "Має збігатися з параметром блока \"Switching Summer/Winter\" "
                            "(PRG → меню конфігурації, пароль 10). Від нього залежить, яку "
                            "уставку записує клімат і чи може він обирати опалення або "
                            "охолодження."),
                    },
                },
            },
        },
        "selector": {
            "framing": {"options": {
                "tcp": t("Modbus TCP gateway (e.g. mbusd)", "Шлюз Modbus TCP (напр. mbusd)"),
                "rtu_over_tcp": t("Transparent serial server (RTU over TCP)",
                                  "Прозорий послідовний сервер (RTU over TCP)"),
            }},
            "switching": {"options": {
                "keyboard": t("From keyboard/serial (factory default)",
                              "З клавіатури/послідовного порту (заводське)"),
                "digital_input": t("From digital input", "Від цифрового входу"),
                "auto_water": t("Auto on water temperature", "Авто за температурою води"),
                "auto_air": t("Auto on air temperature", "Авто за температурою повітря"),
            }},
            "table": {"options": {
                "coil": t("Coils", "Котушки"),
                "discrete": t("Discrete inputs", "Дискретні входи"),
                "holding": t("Holding registers", "Регістри зберігання"),
                "input": t("Input registers", "Вхідні регістри"),
            }},
        },
        "services": {
            "read_registers": {
                "name": t("Read registers", "Зчитати регістри"),
                "description": t(
                    "Reads raw values from one Modbus table through the integration's own "
                    "connection, for research and support. Without an address it reads the "
                    "whole table as the manual lists it. Only reads, never writes. Admin only.",
                    "Зчитує сирі значення з однієї таблиці Modbus через з'єднання інтеграції, "
                    "для досліджень і підтримки. Без адреси зчитує всю таблицю, як у "
                    "посібнику. Лише зчитує, ніколи не записує. Тільки для адміністратора."),
                "fields": {
                    "config_entry_id": {
                        "name": t("Fancoil", "Фанкойл"),
                        "description": t("Which unit, if more than one is configured.",
                                         "Який блок, якщо налаштовано кілька."),
                    },
                    "table": {
                        "name": t("Table", "Таблиця"),
                        "description": t("Which Modbus table to read.",
                                         "Яку таблицю Modbus зчитати."),
                    },
                    "address": {
                        "name": t("Address", "Адреса"),
                        "description": t("First address, from 0 (the manual's number minus "
                                         "one).",
                                         "Перша адреса, від 0 (номер у посібнику мінус один)."),
                    },
                    "count": {
                        "name": t("Count", "Кількість"),
                        "description": t("How many values to read from the address.",
                                         "Скільки значень зчитати від адреси."),
                    },
                },
            },
        },
        "entity": {
            "sensor": _entities(SENSOR, lang),
            "binary_sensor": _entities(BINARY_SENSOR, lang),
            "switch": _entities(COIL, lang),
            "number": _entities(NUMBER, lang),
            "select": _entities(SELECT, lang),
            "climate": {
                "fancoil": {
                    "name": t("Fancoil", "Фанкойл"),
                    "state_attributes": {
                        "fan_mode": {"state": {k: v[lang] for k, v in FAN_SPEED_STATES.items()}},
                    },
                },
            },
        },
        "exceptions": {key: {"message": pair[lang]} for key, pair in EXCEPTIONS.items()},
    }


def render(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def outputs() -> dict[pathlib.Path, str]:
    english, ukrainian = render(build(0)), render(build(1))
    return {
        PACKAGE / "strings.json": english,
        PACKAGE / "translations" / "en.json": english,
        PACKAGE / "translations" / "uk.json": ukrainian,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if any file is stale")
    args = parser.parse_args()
    stale = []
    for path, text in outputs().items():
        if path.exists() and path.read_text(encoding="utf-8") == text:
            continue
        stale.append(path)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    for path in stale:
        print(f"{'stale' if args.check else 'wrote'}: {path.relative_to(ROOT)}")
    return 1 if args.check and stale else 0


if __name__ == "__main__":
    sys.exit(main())
