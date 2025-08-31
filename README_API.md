# API для управления конфигурацией

## Описание

API сервис для управления конфигурацией системы видеомониторинга. Позволяет получать, обновлять отдельные параметры и весь конфиг целиком.

## Endpoints

### GET /config
Получить всю конфигурацию

**Response:**
```json
{
  "cigarette": {
    "enable": true,
    "duration": 0.1,
    "threshold": 0.8
  },
  "system": {
    "model": "./yolo11",
    "rtsp_stream_url": "rtsp://192.168.0.173:8554/stream"
  }
}
```

### GET /config/{section}
Получить конкретную секцию конфигурации

**Example:** `GET /config/cigarette`

**Response:**
```json
{
  "enable": true,
  "duration": 0.1,
  "threshold": 0.8
}
```

### PATCH /config
Обновить отдельный параметр

**Request Body:**
```json
{
  "section": "cigarette",
  "key": "enable",
  "value": false
}
```

**Response:**
```json
{
  "status": "ok",
  "updated": {
    "section": "cigarette",
    "key": "enable",
    "value": false
  }
}
```

### PUT /config
Обновить весь конфиг целиком

**Request Body:** Полная конфигурация в формате JSON

**Response:**
```json
{
  "status": "ok",
  "message": "Config updated successfully"
}
```

## Запуск API сервиса

```bash
cd opi5test/api
docker-compose up -d
```

Или напрямую:

```bash
cd opi5test/api
python app.py
```

## Тестирование

```bash
cd web
python test_api.py
```

## Использование в веб-интерфейсе

Веб-интерфейс автоматически использует API для:
- Загрузки конфигурации при запуске
- Обновления параметров при изменении
- Управления чекбоксами enable/disable для тревог

## Структура конфигурации

```yaml
cigarette:
  enable: true          # Включить/выключить детекцию курения
  duration: 0.1         # Длительность в секундах
  threshold: 0.8        # Порог уверенности

closed_eyes:
  enable: true          # Включить/выключить детекцию закрытых глаз
  duration: 1.0
  threshold: 0.8

# ... другие типы нарушений

system:
  model: './yolo11'     # Путь к модели YOLO
  rtsp_stream_url: 'rtsp://192.168.0.173:8554/stream'

rockchip:
  ip: '192.168.0.173'  # IP адрес Rockchip
  api_port: 8000        # Порт API сервиса
```

## Обработка ошибок

API возвращает соответствующие HTTP коды:
- `200` - успешное выполнение
- `404` - секция или параметр не найдены
- `500` - ошибка сохранения конфигурации

## CORS

API настроен для работы с веб-интерфейсом и разрешает запросы с любого домена.
