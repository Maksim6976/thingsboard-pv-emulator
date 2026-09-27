# ПВ-01 — ThingsBoard Community Edition + эмулятор приточно-вытяжной установки

Тестовое задание: локальный ThingsBoard CE в Docker Compose и реалистичный MQTT-эмулятор ПВУ.

## Архитектура

```text
Python PV emulator
       |
       | MQTT / v1/devices/me/telemetry
       v
ThingsBoard CE :1883 / :8080
       |
       v
PostgreSQL (Docker volume)
```

## Состав

- `docker-compose.yml` — ThingsBoard CE + PostgreSQL, restart policy, environment variables, persistent volume.
- `emulator/pv_emulator.py` — эмуляция ПВУ с динамикой температур, клапанов, вентиляторов и загрязнения фильтра.
- `emulator/requirements.txt` — зависимости Python.
- `.env.example` — пример переменных окружения.

## Запуск

### 1. Требования

- Docker Desktop с включённым Docker Engine.
- Python 3.11+.

### 2. Конфигурация

Скопировать `.env.example` в `.env` и задать пароль PostgreSQL и позже токен устройства:

```powershell
Copy-Item .env.example .env
```

### 3. Инициализация ThingsBoard

Из каталога проекта:

```powershell
docker compose run --rm -e INSTALL_TB=true -e LOAD_DEMO=true thingsboard-ce
```

После успешной инициализации:

```powershell
docker compose up -d
```

Открыть http://localhost:8080.

После установки с demo-данными для работы с устройствами используй Tenant Administrator `tenant@thingsboard.org` / `tenant`. Для локального теста это допустимо; наружу сервис не публикуется.

### 4. Создать устройство

В ThingsBoard создать устройство:

- Name: `PV-01`
- Device profile: `default`

Открыть credentials устройства и скопировать Access Token в `.env`:

```text
TB_DEVICE_TOKEN=...
```

### 5. Запустить эмулятор

```powershell
cd emulator
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python pv_emulator.py
```

Эмулятор публикует telemetry каждые 2 секунды.

## Телеметрия

| Key | Meaning | Unit |
|---|---|---|
| `outdoor_temperature` | наружная температура | °C |
| `supply_temperature` | температура приточного воздуха | °C |
| `temperature_setpoint` | уставка | °C |
| `supply_fan_rpm` | обороты приточного вентилятора | rpm |
| `exhaust_fan_rpm` | обороты вытяжного вентилятора | rpm |
| `filter_differential_pressure` | перепад давления на фильтре | Pa |
| `damper_position` | положение воздушной заслонки | % |
| `heating_valve_position` | клапан нагрева | % |
| `cooling_valve_position` | клапан охлаждения | % |
| `humidity` | влажность | % |
| `running` | установка работает | bool |
| `alarm` | общий аварийный статус | bool |
| `filter_clogged` | фильтр загрязнён | bool |
| `fan_fault` | авария вентилятора | bool |

## Логика модели

- Наружная температура меняется плавно, с небольшой случайной составляющей.
- Уставка периодически изменяется.
- Приточная температура не скачет к уставке мгновенно: используется инерционная модель.
- При отклонении температуры изменяется положение клапана нагрева/охлаждения.
- Обороты вентиляторов выходят на номинал плавно.
- Перепад давления фильтра постепенно растёт, имитируя загрязнение.
- В демонстрационном режиме раз в 180 секунд создаётся кратковременная неисправность вентилятора, чтобы можно было показать индикацию аварии на дашборде.

Параметр `FILTER_GROWTH_PA_PER_MIN` можно увеличить для быстрой демонстрации загрязнения фильтра.

## Dashboard

Рекомендуемая компоновка:

1. Карточки текущих значений: приточная температура, наружная температура, уставка, влажность, перепад давления.
2. Индикаторы: Работа, Авария, Загрязнение фильтра, Авария вентилятора.
3. Line chart: `outdoor_temperature`, `supply_temperature`, `temperature_setpoint`.
4. Line chart: `filter_differential_pressure`.
5. Карточки/индикаторы положения клапанов и заслонки.
6. Значения оборотов приточного и вытяжного вентиляторов.

Для графиков рекомендуется использовать окно `Last 10 minutes` во время демонстрации.

## Проверка сохранения данных

```powershell
docker compose restart thingsboard-ce
```

После перезапуска данные должны оставаться в PostgreSQL volume `tb-pv-postgres-data`.

## Остановка

```powershell
docker compose down
```

Данные сохраняются, поскольку PostgreSQL использует named volume. Не выполнять `docker compose down -v`, если нужно сохранить данные.
