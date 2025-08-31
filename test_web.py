#!/usr/bin/env python3
"""
Скрипт для тестирования веб-интерфейса
"""

import requests
import time

def test_web_interface():
    """Тестирует доступность веб-интерфейса"""
    try:
        response = requests.get("http://localhost:7860", timeout=10)
        print(f"Web interface: {response.status_code}")
        if response.status_code == 200:
            print("✅ Веб-интерфейс доступен")
        else:
            print(f"❌ Веб-интерфейс недоступен: {response.status_code}")
    except Exception as e:
        print(f"❌ Ошибка подключения к веб-интерфейсу: {e}")

def test_api_connection():
    """Тестирует подключение к API из веб-интерфейса"""
    try:
        # Имитируем запрос, который делает веб-интерфейс
        response = requests.get("http://192.168.0.173:8000/config", timeout=10)
        print(f"API connection: {response.status_code}")
        if response.status_code == 200:
            print("✅ API доступен")
            config = response.json()
            print(f"   Загружено секций: {len(config)}")
        else:
            print(f"❌ API недоступен: {response.status_code}")
    except Exception as e:
        print(f"❌ Ошибка подключения к API: {e}")

if __name__ == "__main__":
    print("Testing web interface and API connection...")
    print("=" * 60)
    
    test_web_interface()
    print()
    
    test_api_connection()
    print()
    
    print("Testing completed!")
