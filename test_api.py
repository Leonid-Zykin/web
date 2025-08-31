#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работы API
"""

import requests
import json

API_BASE_URL = "http://192.168.0.173:8000"

def test_get_config():
    """Тестирует получение конфигурации"""
    try:
        response = requests.get(f"{API_BASE_URL}/config", timeout=10)
        print(f"GET /config: {response.status_code}")
        if response.status_code == 200:
            config = response.json()
            print(f"Config loaded: {len(config)} sections")
            for section, data in config.items():
                print(f"  {section}: {len(data)} params")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

def test_update_param():
    """Тестирует обновление параметра"""
    try:
        update_data = {
            "section": "cigarette",
            "key": "enable",
            "value": False
        }
        response = requests.patch(f"{API_BASE_URL}/config", json=update_data, timeout=10)
        print(f"PATCH /config: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"Updated: {result}")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

def test_update_full_config():
    """Тестирует обновление всего конфига"""
    try:
        # Сначала получаем текущий конфиг
        response = requests.get(f"{API_BASE_URL}/config", timeout=10)
        if response.status_code != 200:
            print("Failed to get current config")
            return
        
        config = response.json()
        
        # Изменяем один параметр
        if 'cigarette' in config:
            config['cigarette']['enable'] = True
        
        # Отправляем обновленный конфиг
        response = requests.put(f"{API_BASE_URL}/config", json=config, timeout=10)
        print(f"PUT /config: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"Full config updated: {result}")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("Testing API endpoints...")
    print("=" * 50)
    
    test_get_config()
    print()
    
    test_update_param()
    print()
    
    test_update_full_config()
    print()
    
    print("Testing completed!")
