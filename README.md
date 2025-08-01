# Видеомониторинг и настройки (Gradio)

## Описание

Веб-приложение для просмотра двух RTSP-потоков и редактирования всех параметров файла `config.yaml` через удобный интерфейс. Все изменения можно сохранить или сбросить к значениям из файла. Интерфейс полностью на русском языке.

## Запуск через Docker Compose

1. Убедитесь, что файл `opi5test/core/config.yaml` существует и содержит нужные параметры.
2. Перейдите в папку `web`:
   ```bash
   cd web
   ```
3. Соберите и запустите контейнер:
   ```bash
   docker-compose up --build
   ```
4. Откройте браузер и перейдите по адресу: [http://localhost:7860](http://localhost:7860)

5. Для остановки контейнера перейдите в папку `web` и выполните следующую команду:

   ```bash
   docker-compose down
   ```
   
## Функционал
- Два окна для просмотра RTSP-потоков (требуется прокси для реального видео).
- Два поля для ввода RTSP-URL.
- Все параметры из `config.yaml` доступны для редактирования.
- Кнопка "Сохранить" — сохраняет изменения в `config.yaml`.
- Кнопка "Сбросить" — возвращает значения из файла.

---

**Внимание:** Для реального отображения RTSP-потоков в браузере требуется проксирование потока в HLS/WebRTC. В текущей версии реализована заглушка для визуализации URL. 

## Важно
В файле `config.yaml` параметр `alarm_server_ip` должен быть установлен в IP-адрес машины, где запущен Gradio-интерфейс (gradio-app). Если приложение запускается в Docker, используйте внешний IP хоста. Тревоги из ядра должны отправляться на этот адрес и порт, указанные в `alarm_server_ip` и `alarm_server_port`. 